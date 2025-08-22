# -*- coding: utf-8 -*-
from collections import defaultdict
from odoo import http
from odoo.http import request
from odoo.fields import Datetime, Date
from datetime import datetime as py_dt, time as py_time
import json, pytz

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

def _get_tzname(params):
    # Prioridad: tz del body → tz del contexto → tz del usuario → UTC
    return (params.get('tz')
            or request.env.context.get('tz')
            or request.env.user.tz
            or 'UTC')

def _parse_local_dt(val, tzname):
    """'YYYY-MM-DD' o 'YYYY-MM-DD HH:MM:SS' -> datetime *aware* en tz local."""
    if not val:
        return None
    try:
        dt = Datetime.from_string(val)   # naive
    except Exception:
        try:
            d = Date.from_string(val)
            dt = Datetime.from_string(f"{d} 00:00:00")
        except Exception:
            return None
    tz = pytz.timezone(tzname)
    return tz.localize(dt)

def _local_to_utc_str(local_dt):
    """local aware -> UTC naive string (para dominios)."""
    if not local_dt:
        return None
    dt_utc = local_dt.astimezone(pytz.UTC).replace(tzinfo=None)
    return Datetime.to_string(dt_utc)

def _utc_str_to_local_date(utc_str, tzname):
    """UTC naive string -> date en tz local."""
    if not utc_str:
        return None
    tz = pytz.timezone(tzname)
    dt_utc = Datetime.from_string(utc_str).replace(tzinfo=pytz.UTC)
    return dt_utc.astimezone(tz).date()

def _utc_str_to_local_date_str(utc_str, tzname):
    """UTC naive string -> 'YYYY-MM-DD' en tz local."""
    d = _utc_str_to_local_date(utc_str, tzname)
    return Date.to_string(d) if d else ""

def _today_local_date(tzname):
    tz = pytz.timezone(tzname)
    now_utc = py_dt.utcnow().replace(tzinfo=pytz.UTC)
    return now_utc.astimezone(tz).date()

def _today_min_utc_str(tzname):
    """Hoy 00:00:00 local -> UTC naive string."""
    tz = pytz.timezone(tzname)
    today = _today_local_date(tzname)
    local_min = tz.localize(py_dt.combine(today, py_time.min))
    return Datetime.to_string(local_min.astimezone(pytz.UTC).replace(tzinfo=None))

def _normalize_states_filter(states_q):
    """
    Convierte 'state' del body (str o lista) en lista normalizada en minúsculas.
    Acepta 'quotation' como sinónimo de 'available'.
    """
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

# -------------------- Controller --------------------
class RentalCalendarAPI(http.Controller):
    # Estado técnico -> etiqueta UI (lo que ve el calendario)
    TECH2UI = {
        'draft':  'available',        # Quotation → Available
        'sent':   'quotation_sent',   # no se devuelve salvo que lo pidan explícitamente
        'sale':   'sale',
        'done':   'done',
        'cancel': 'cancelled',
        # futuros (cuando existan en tu DB, entran directos)
        'option':   'option',
        'preboard': 'preboard',
        'invoiced': 'invoiced',
    }

    # Orden natural de salida
    ALLOWED_UI_STATES = ['available', 'option', 'preboard', 'invoiced', 'cancelled']

    @http.route('/api/availability/calendar', type='http',
                auth='public', methods=['POST'], csrf=False)
    def availability_calendar(self, **post):
        params   = _read_params(post)
        tzname   = _get_tzname(params)

        # ventana solicitada (local)
        start_loc = _parse_local_dt(params.get('from') or params.get('start'), tzname)
        end_loc   = _parse_local_dt(params.get('to')   or params.get('end'),   tzname)
        if not (start_loc and end_loc):
            return request.make_response(
                json.dumps({"error": "Debe enviar 'from' y 'to' (YYYY-MM-DD o YYYY-MM-DD HH:MM:SS)"}),
                headers=[('Content-Type','application/json')], status=400
            )

        id_boat   = params.get('id_boat')
        limit     = int(params.get('limit', 1000))
        booking_q = params.get('booking')   # filtro opcional: ilike sobre name
        states_q  = _normalize_states_filter(params.get('state'))  # str o lista → lista o None

        # dominios en UTC
        start_utc = _local_to_utc_str(start_loc)
        end_utc   = _local_to_utc_str(end_loc)
        today_utc_min = _today_min_utc_str(tzname)
        today_loc = _today_local_date(tzname)

        # --------- Buscar pedidos base (overlap + vigentes) ----------
        domain = [
            ('embarcacion_id', '!=', False),
            ('rental_start_date', '<=', end_utc),      # overlap
            ('rental_return_date', '>=', start_utc),   # overlap
            ('rental_return_date', '>=', today_utc_min) # vigentes (no pasados)
        ]
        if id_boat not in (None, ""):
            try:
                domain.append(('embarcacion_id', '=', int(id_boat)))
            except Exception:
                return request.make_response(
                    json.dumps({"error": "id_boat debe ser numérico"}),
                    headers=[('Content-Type','application/json')], status=400
                )
        if booking_q:
            domain.append(('name', 'ilike', booking_q))

        Order = request.env['sale.order'].sudo()
        fields_list = ['name', 'state', 'embarcacion_id', 'rental_start_date', 'rental_return_date']
        orders = Order.search_read(domain, fields_list, order='rental_start_date asc', limit=limit)

        # --------- Cargar periodos activos y bloqueos por barco ----------
        boat_ids = list({o['embarcacion_id'][0] for o in orders if o.get('embarcacion_id')})
        Avail = request.env['rental.availability'].sudo()
        Block = request.env['rental.blocked.period'].sudo()

        # Periodos activos (date_from/date_to son fechas sin hora)
        periods = Avail.search_read(
            [('boat_id', 'in', boat_ids), ('state', '=', 'active')],
            ['boat_id', 'date_from', 'date_to']
        )
        periods_by_boat = defaultdict(list)
        for p in periods:
            bid = p['boat_id'][0]
            try:
                d1 = Date.from_string(p['date_from'])
                d2 = Date.from_string(p['date_to'])
            except Exception:
                continue
            if d1 and d2:
                periods_by_boat[bid].append((d1, d2))

        # Bloqueos (un día)
        locks = Block.search_read(
            [('boat_id', 'in', boat_ids)],
            ['boat_id', 'date_blocked', 'block_type']
        )
        locks_by_boat = defaultdict(list)
        for b in locks:
            bid = b['boat_id'][0]
            try:
                d = Date.from_string(b['date_blocked'])
            except Exception:
                continue
            if d:
                # tratamos bloqueo como [d, d]
                locks_by_boat[bid].append((d, d, b.get('block_type')))

        # --------- Construir, filtrar por disponibilidad/bloqueos y agrupar ----------
        # Qué claves devolver: si pidieron 'state', solo esas; si no, todas.
        if states_q:
            # Filtra contra el set permitido y respeta el orden natural
            output_keys = [k for k in self.ALLOWED_UI_STATES if k in states_q]
        else:
            output_keys = list(self.ALLOWED_UI_STATES)

        grouped = {key: [] for key in output_keys}

        for o in orders:
            if not o.get('embarcacion_id'):
                continue
            bid = o['embarcacion_id'][0]

            # Fechas en zona local (date) para comparaciones y para responder
            o_start_loc_d = _utc_str_to_local_date(o.get('rental_start_date'), tzname)
            o_end_loc_d   = _utc_str_to_local_date(o.get('rental_return_date'), tzname)
            if not (o_start_loc_d and o_end_loc_d):
                continue
            # vigentes (doble seguridad por si la TZ lo cambia)
            if o_end_loc_d < today_loc:
                continue

            # Debe caer COMPLETO dentro de algún periodo activo del barco
            per_list = periods_by_boat.get(bid, [])
            if not any(p_start <= o_start_loc_d and p_end >= o_end_loc_d for (p_start, p_end) in per_list):
                continue

            # No debe cruzarse con bloqueos del barco
            if any(l_start <= o_end_loc_d and l_end >= o_start_loc_d for (l_start, l_end, _t) in locks_by_boat.get(bid, [])):
                continue

            # Mapear estado técnico → UI
            tech = (o.get('state') or '').strip()
            ui_state = self.TECH2UI.get(tech, tech)  # si aparece un futuro tal cual, lo deja igual

            # ¿Está permitido y requerido?
            if ui_state not in self.ALLOWED_UI_STATES:
                continue
            if ui_state not in grouped:   # si pidieron filtro y este estado no está solicitado
                continue

            grouped[ui_state].append({
                "booking_number": o['name'],
                "boat_name": o['embarcacion_id'][1] if o.get('embarcacion_id') else "",
                "state": ui_state,
                "start_date": Date.to_string(o_start_loc_d),  # sin hora
                "end_date":   Date.to_string(o_end_loc_d),    # sin hora
            })

        # Ordenar cada lista por start_date asc, luego booking_number
        for k in grouped:
            grouped[k].sort(key=lambda x: (x.get('start_date') or '', x.get('booking_number') or ''))

        # Solo devolvemos las claves solicitadas (o todas si no hubo filtro)
        ordered_payload = {k: grouped[k] for k in output_keys}

        return request.make_response(
            json.dumps(ordered_payload),
            headers=[('Content-Type','application/json')], status=200
        )
