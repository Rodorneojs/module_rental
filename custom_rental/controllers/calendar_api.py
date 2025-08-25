# -*- coding: utf-8 -*-
from collections import defaultdict
from odoo import http
from odoo.http import request
from odoo.fields import Datetime, Date
from odoo.osv.expression import AND, OR
from datetime import datetime as py_dt, time as py_time
import json, pytz, jwt

MAX_LIMIT = 5000  # techo para proteger el servidor

# -------------------- Helpers --------------------
def _read_params(post):
    try:
        ct = (request.httprequest.content_type or "").lower()
    except Exception:
        ct = ""
    if "application/json" in ct:
        try:
            raw = request.httprequest.get_data(cache=True, as_text=True) or "{}"
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return post

def _jwt_secret():
    return request.env['ir.config_parameter'].sudo().get_param(
        'custom_contact.jwt_secret_key',
        default='clave_ultra_secreta_cambia_esto'
    )

def _get_bearer_token():
    auth = (request.httprequest.headers.get('Authorization') or '').strip()
    if not auth or not auth.lower().startswith('bearer '):
        return None
    return auth.split(' ', 1)[1].strip()

def _verify_jwt(token):
    try:
        return jwt.decode(token, _jwt_secret(), algorithms=['HS256'])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
    except Exception:
        return None

def _get_tzname(params):
    return (params.get('tz')
            or request.env.context.get('tz')
            or request.env.user.tz
            or 'UTC')

def _parse_local_dt(val, tzname, is_end=False):
    """'YYYY-MM-DD' o 'YYYY-MM-DD HH:MM:SS' -> datetime aware en tz local."""
    if not val:
        return None
    val_str = str(val).strip()
    has_time = (' ' in val_str) or ('T' in val_str)
    try:
        if has_time:
            dt = Datetime.from_string(val_str)  # naive
        else:
            hhmmss = "23:59:59" if is_end else "00:00:00"
            dt = Datetime.from_string(f"{val_str} {hhmmss}")
    except Exception:
        try:
            d = Date.from_string(val_str)
            hhmmss = "23:59:59" if is_end else "00:00:00"
            dt = Datetime.from_string(f"{d} {hhmmss}")
        except Exception:
            return None
    tz = pytz.timezone(tzname)
    return tz.localize(dt)

def _local_to_utc_str(local_dt):
    if not local_dt:
        return None
    dt_utc = local_dt.astimezone(pytz.UTC).replace(tzinfo=None)
    return Datetime.to_string(dt_utc)

def _utc_str_to_local_dt(utc_str, tzname):
    if not utc_str:
        return None
    tz = pytz.timezone(tzname)
    dt_utc = Datetime.from_string(utc_str).replace(tzinfo=pytz.UTC)
    return dt_utc.astimezone(tz)

def _utc_str_to_local_date(utc_str, tzname):
    dt_loc = _utc_str_to_local_dt(utc_str, tzname)
    return dt_loc.date() if dt_loc else None

def _utc_str_to_local_dt_str(utc_str, tzname):
    dt_loc = _utc_str_to_local_dt(utc_str, tzname)
    return dt_loc.strftime("%Y-%m-%d %H:%M:%S") if dt_loc else ""

def _today_local_date(tzname):
    tz = pytz.timezone(tzname)
    now_utc = py_dt.utcnow().replace(tzinfo=pytz.UTC)
    return now_utc.astimezone(tz).date()

def _today_min_utc_str(tzname):
    tz = pytz.timezone(tzname)
    today = _today_local_date(tzname)
    local_min = tz.localize(py_dt.combine(today, py_time.min))
    return Datetime.to_string(local_min.astimezone(pytz.UTC).replace(tzinfo=None))

def _normalize_states_filter(states_q):
    if not states_q:
        return None
    lst = states_q if isinstance(states_q, list) else [states_q]
    norm = []
    for s in lst:
        s = str(s).strip().lower()
        if s == 'quotation':
            s = 'available'
        norm.append(s)
    return norm

def _float_to_hhmm(val):
    if val in (None, False, ''):
        return ""
    try:
        f = float(val)
    except Exception:
        return ""
    h = int(f)
    m = int(round((f - h) * 60))
    return f"{h:02d}:{m:02d}"

def _merge_date_time_str(date_str, time_str, is_end=False):
    """Une 'YYYY-MM-DD' + 'HH:MM' -> 'YYYY-MM-DD HH:MM:SS' (con segundos)."""
    hhmm = time_str if time_str else ("23:59" if is_end else "00:00")
    return f"{date_str} {hhmm}:00"

def _norm_schedule_state(raw):
    s = str(raw or "").lower().strip()
    s = s.replace(" ", "").replace("-", "").replace("_", "")
    if s in ("available",):
        return "available"
    if s in ("option",):
        return "option"
    if s in ("preonboard", "preonboarding", "preboard"):
        return "preboard"
    if s in ("invoiced", "invoice"):
        return "invoiced"
    if s in ("cancelled", "canceled"):
        return "cancelled"
    return None

# -------------------- Controller --------------------
class RentalCalendarAPI(http.Controller):
    TECH2UI = {
        'draft':  'available',
        'sent':   'quotation_sent',
        'sale':   'sale',
        'done':   'done',
        'cancel': 'cancelled',
    }

    ALLOWED_UI_STATES = ['available', 'option', 'preboard', 'invoiced', 'cancelled']

    @http.route('/api/availability/calendar', type='http',
                auth='public', methods=['POST'], csrf=False)
    def availability_calendar(self, **post):
        # ---- 0) Auth Bearer JWT ----
        token = _get_bearer_token()
        if not token:
            return request.make_response(
                json.dumps({"error": "Unauthorized", "detail": "Missing Authorization: Bearer <token>"}),
                headers=[('Content-Type', 'application/json')], status=401
            )
        payload = _verify_jwt(token)
        if not payload:
            return request.make_response(
                json.dumps({"error": "Unauthorized", "detail": "Invalid or expired token"}),
                headers=[('Content-Type', 'application/json')], status=401
            )
        contact_id = payload.get('contact_id')
        if not contact_id or not request.env['res.partner'].sudo().browse(contact_id).exists():
            return request.make_response(
                json.dumps({"error": "Unauthorized", "detail": "Contact not found"}),
                headers=[('Content-Type', 'application/json')], status=401
            )

        # ---- 1) Parámetros ----
        params = _read_params(post)
        tzname = _get_tzname(params)

        # Fechas opcionales (para permitir búsqueda por booking sin fechas)
        start_param = params.get('from') or params.get('start')
        end_param   = params.get('to')   or params.get('end')

        start_loc = _parse_local_dt(start_param, tzname, is_end=False) if start_param else None
        end_loc   = _parse_local_dt(end_param,   tzname, is_end=True)  if end_param   else None

        # Filtros independientes:
        # - Si hay rango de fechas, deben venir ambas.
        # - Si NO hay rango pero sí booking/booking_number, se permite (sin fechas).
        booking_ilike  = params.get('booking')           # parcial
        booking_exact  = params.get('booking_number')    # exacto
        has_range      = bool(start_loc and end_loc)
        has_booking    = bool(booking_ilike or booking_exact)

        if not has_range and not has_booking:
            return request.make_response(
                json.dumps({"error": "Debe enviar rango 'from'/'to' o bien 'booking'/'booking_number'."}),
                headers=[('Content-Type','application/json')], status=400
            )
        if (start_loc and not end_loc) or (end_loc and not start_loc):
            return request.make_response(
                json.dumps({"error": "Si usa fechas, envíe ambas: 'from' y 'to'."}),
                headers=[('Content-Type','application/json')], status=400
            )

        # harden limit (protege el servidor)
        try:
            raw_limit = int(params.get('limit', 1000))
        except Exception:
            raw_limit = 1000
        limit = max(1, min(raw_limit, MAX_LIMIT))

        id_boat  = params.get('id_boat')
        states_q = _normalize_states_filter(params.get('state'))

        # ---- 2) Rango y “vigentes” ----
        today_utc_min  = _today_min_utc_str(tzname)
        today_loc      = _today_local_date(tzname)

        domain_parts = []

        # Vigentes siempre (no devolver pasadas)
        vigente = OR([[('rental_return_date', '>=', today_utc_min)],
                      [('x_turn_date', '>=', Date.to_string(today_loc))]])
        domain_parts.append(vigente)

        # Si hay rango, agregar overlaps
        if has_range:
            start_utc       = _local_to_utc_str(start_loc)
            end_utc         = _local_to_utc_str(end_loc)
            start_date_loc  = start_loc.date()
            end_date_loc    = end_loc.date()

            overlap_rental = [('rental_start_date', '<=', end_utc),
                              ('rental_return_date', '>=', start_utc)]
            overlap_turn   = [('x_turn_date', '>=', Date.to_string(start_date_loc)),
                              ('x_turn_date', '<=', Date.to_string(end_date_loc))]
            overlap_any    = OR([overlap_rental, overlap_turn])
            domain_parts.append(overlap_any)

        # Debe tener barco (por cualquiera de los 2 campos)
        boat_present = OR([[('embarcacion_id', '!=', False)],
                           [('x_turn_yacht_id', '!=', False)]])
        domain_parts.append(boat_present)

        # Filtro por barco (independiente)
        if id_boat not in (None, ""):
            try:
                id_boat_int = int(id_boat)
            except Exception:
                return request.make_response(
                    json.dumps({"error": "id_boat debe ser numérico"}),
                    headers=[('Content-Type','application/json')], status=400
                )
            by_boat = OR([[('embarcacion_id', '=', id_boat_int)],
                          [('x_turn_yacht_id', '=', id_boat_int)]])
            domain_parts.append(by_boat)

        # Filtro por booking (independiente)
        if booking_exact:
            domain_parts.append([('name', '=', str(booking_exact))])
        elif booking_ilike:
            domain_parts.append([('name', 'ilike', booking_ilike)])

        domain = AND(domain_parts)

        Order = request.env['sale.order'].sudo()
        fields_list = [
            'name', 'state', 'x_schedule_state',
            'embarcacion_id', 'x_turn_yacht_id',
            'rental_start_date', 'rental_return_date',
            'x_turn_date', 'x_turn_hour_from', 'x_turn_hour_to',
        ]
        # ordenar considerando ambos tipos de eventos
        orders = Order.search_read(domain, fields_list,
                                   order='x_turn_date asc, rental_start_date asc, id asc',
                                   limit=limit)

        # ---- 3) Periodos activos y bloqueos (batched) ----
        boat_ids = set()
        for o in orders:
            if o.get('x_turn_yacht_id'):
                boat_ids.add(o['x_turn_yacht_id'][0])
            if o.get('embarcacion_id'):
                boat_ids.add(o['embarcacion_id'][0])
        boat_ids = list(boat_ids)

        Avail = request.env['rental.availability'].sudo()
        Block = request.env['rental.blocked.period'].sudo()

        periods_by_boat = defaultdict(list)
        if boat_ids:
            periods = Avail.search_read(
                [('boat_id', 'in', boat_ids), ('state', '=', 'active')],
                ['boat_id', 'date_from', 'date_to']
            )
            for p in periods:
                bid = p['boat_id'][0]
                try:
                    d1 = Date.from_string(p['date_from'])
                    d2 = Date.from_string(p['date_to'])
                except Exception:
                    continue
                if d1 and d2:
                    periods_by_boat[bid].append((d1, d2))

        locks_by_boat = defaultdict(list)
        if boat_ids:
            locks = Block.search_read(
                [('boat_id', 'in', boat_ids)],
                ['boat_id', 'date_blocked', 'block_type']
            )
            for b in locks:
                bid = b['boat_id'][0]
                try:
                    d = Date.from_string(b['date_blocked'])
                except Exception:
                    continue
                if d:
                    locks_by_boat[bid].append((d, d, b.get('block_type')))

        # ---- 4) Construcción + filtros de disponibilidad/bloqueos ----
        output_keys = (self.ALLOWED_UI_STATES if not states_q
                       else [k for k in self.ALLOWED_UI_STATES if k in states_q])
        grouped = {key: [] for key in output_keys}

        for o in orders:
            boat_tuple = o.get('x_turn_yacht_id') or o.get('embarcacion_id')
            if not boat_tuple:
                continue
            bid, bname = boat_tuple[0], boat_tuple[1]

            per_list = periods_by_boat.get(bid, ())
            if not per_list:
                continue
            lock_list = locks_by_boat.get(bid, ())

            x_turn_date = o.get('x_turn_date')
            if x_turn_date:
                # ---- Caso turnos de un día ----
                try:
                    d_turn = Date.from_string(x_turn_date)
                except Exception:
                    continue
                if d_turn < today_loc:
                    continue

                if not any(p_start <= d_turn <= p_end for (p_start, p_end) in per_list):
                    continue
                if any(l_start <= d_turn <= l_end for (l_start, l_end, _t) in lock_list):
                    continue

                date_str      = Date.to_string(d_turn)
                start_hhmm    = _float_to_hhmm(o.get('x_turn_hour_from'))
                end_hhmm      = _float_to_hhmm(o.get('x_turn_hour_to'))
                start_dt_str  = _merge_date_time_str(date_str, start_hhmm, is_end=False)
                end_dt_str    = _merge_date_time_str(date_str, end_hhmm,   is_end=True)

            else:
                # ---- Caso rango rental_* clásico ----
                s_date = _utc_str_to_local_date(o.get('rental_start_date'), tzname)
                e_date = _utc_str_to_local_date(o.get('rental_return_date'), tzname)
                if not (s_date and e_date):
                    continue
                if e_date < today_loc:
                    continue

                if not any(p_start <= s_date and p_end >= e_date for (p_start, p_end) in per_list):
                    continue
                if any(l_start <= e_date and l_end >= s_date for (l_start, l_end, _t) in lock_list):
                    continue

                start_dt_str = _utc_str_to_local_dt_str(o.get('rental_start_date'), tzname)
                end_dt_str   = _utc_str_to_local_dt_str(o.get('rental_return_date'), tzname)

            # Estado UI
            ui_state = None
            if 'x_schedule_state' in o and o.get('x_schedule_state'):
                ui_state = _norm_schedule_state(o.get('x_schedule_state'))
            if not ui_state:
                tech = (o.get('state') or '').strip()
                ui_state = self.TECH2UI.get(tech, tech)

            if ui_state not in self.ALLOWED_UI_STATES or ui_state not in grouped:
                continue

            grouped[ui_state].append({
                "booking_number": o['name'],
                "boat_name": bname or "",
                "state": ui_state,
                "start_date": start_dt_str,  # YYYY-MM-DD HH:MM:SS
                "end_date":   end_dt_str,    # YYYY-MM-DD HH:MM:SS
            })

        # ordenar en memoria
        for k in grouped:
            grouped[k].sort(key=lambda x: (x.get('start_date') or '', x.get('booking_number') or ''))

        # ---- 5) Respuesta (sin buckets vacíos) ----
        if states_q:
            ordered_payload = {k: grouped[k] for k in output_keys if grouped[k]}
        else:
            ordered_payload = {k: v for k, v in grouped.items() if v}

        return request.make_response(
            json.dumps(ordered_payload),
            headers=[('Content-Type','application/json')], status=200
        )
