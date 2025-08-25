# -*- coding: utf-8 -*-
from collections import defaultdict
from odoo import http
from odoo.http import request
from odoo.fields import Datetime, Date
from odoo.osv.expression import AND, OR
from datetime import datetime as py_dt, time as py_time
import json, pytz, jwt
import logging, traceback

_logger = logging.getLogger(__name__)

MAX_LIMIT = 5000  # techo para proteger el servidor

# -------------------- Helpers (reutilizados y recortados a lo necesario) --------------------
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

def _utc_str_to_local_date_str(utc_str, tzname):
    dt_loc = _utc_str_to_local_dt(utc_str, tzname)
    return Date.to_string(dt_loc.date()) if dt_loc else ""

def _utc_str_to_local_date(utc_str, tzname):
    dt_loc = _utc_str_to_local_dt(utc_str, tzname)
    return dt_loc.date() if dt_loc else None

def _today_local_date(tzname):
    tz = pytz.timezone(tzname)
    now_utc = py_dt.utcnow().replace(tzinfo=pytz.UTC)
    return now_utc.astimezone(tz).date()

def _normalize_states_filter(states_q):
    """
    Acepta string o lista. Devuelve lista normalizada en minúsculas.
    'quotation' se trata como 'available'.
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

def _norm_schedule_state(raw):
    s = str(raw or "").lower().strip()
    s = s.replace(" ", "").replace("-", "").replace("_", "")
    if s in ("available",): return "available"
    if s in ("option",):    return "option"
    if s in ("preonboard","preonboarding","preboard"): return "preboard"
    if s in ("invoiced","invoice"): return "invoiced"
    if s in ("cancelled","canceled"): return "cancelled"
    return None

def _sel_label(model, field_name, value):
    """Devuelve la etiqueta legible de un campo selection."""
    try:
        sel = dict(model._fields[field_name].selection)
        return sel.get(value, value or "")
    except Exception:
        return value or ""

def _odo_unit_short(val):
    if not val:
        return ""
    v = str(val).lower()
    if v.startswith('kilometer') or v == 'km':
        return 'km'
    if v.startswith('mile') or v == 'mi':
        return 'mi'
    return v

# -------------------- Controller --------------------
class BookingListAPI(http.Controller):
    # Mapeo estado técnico -> etiqueta UI
    TECH2UI = {
        'draft':  'available',         # Quotation → Available
        'sent':   'quotation_sent',
        'sale':   'sale',
        'done':   'done',
        'cancel': 'cancelled',
    }

    # Estados UI que reconocemos/permitimos filtrar
    ALLOWED_UI_STATES = ['available', 'option', 'preboard', 'invoiced', 'cancelled']
    # Prioridad de orden para los estados
    STATE_ORDER = {s: i for i, s in enumerate(ALLOWED_UI_STATES)}

    @http.route('/api/bookings/list', type='http', auth='public', methods=['POST'], csrf=False)
    def bookings_list(self, **post):
        try:
            # ---- 0) Auth Bearer JWT ----
            token = _get_bearer_token()
            if not token:
                return request.make_response(
                    json.dumps({"error": "Unauthorized", "detail": "Missing Authorization: Bearer <token>"}),
                    headers=[('Content-Type','application/json')], status=401
                )
            payload = _verify_jwt(token)
            if not payload:
                return request.make_response(
                    json.dumps({"error": "Unauthorized", "detail": "Invalid or expired token"}),
                    headers=[('Content-Type','application/json')], status=401
                )
            contact_id = payload.get('contact_id')
            if not contact_id or not request.env['res.partner'].sudo().browse(contact_id).exists():
                return request.make_response(
                    json.dumps({"error": "Unauthorized", "detail": "Contact not found"}),
                    headers=[('Content-Type','application/json')], status=401
                )

            # ---- 1) Parámetros ----
            params   = _read_params(post)
            tzname   = _get_tzname(params)

            start_loc = _parse_local_dt(params.get('from') or params.get('start'), tzname, is_end=False)
            end_loc   = _parse_local_dt(params.get('to')   or params.get('end'),   tzname, is_end=True)
            if not (start_loc and end_loc):
                return request.make_response(
                    json.dumps({"error": "Debe enviar 'from' y 'to' (YYYY-MM-DD o YYYY-MM-DD HH:MM:SS)"}),
                    headers=[('Content-Type','application/json')], status=400
                )

            # límites seguros
            try:
                raw_limit = int(params.get('limit', 1000))
            except Exception:
                raw_limit = 1000
            limit = max(1, min(raw_limit, MAX_LIMIT))

            id_boat        = params.get('id_boat')
            booking_ilike  = params.get('booking')           # parcial
            booking_exact  = params.get('booking_number')    # exacto
            customer_q     = params.get('customer')          # parcial sobre partner
            states_q       = _normalize_states_filter(params.get('state'))

            # ---- 2) Dominio base (overlap renting + con barco) ----
            start_utc = _local_to_utc_str(start_loc)
            end_utc   = _local_to_utc_str(end_loc)

            domain = [
                ('rental_start_date', '<=', end_utc),
                ('rental_return_date', '>=', start_utc),
                '|', ('x_turn_yacht_id', '!=', False), ('embarcacion_id', '!=', False),
            ]

            if id_boat not in (None, ""):
                try:
                    id_boat_int = int(id_boat)
                except Exception:
                    return request.make_response(
                        json.dumps({"error": "id_boat debe ser numérico"}),
                        headers=[('Content-Type','application/json')], status=400
                    )
                domain += ['|', ('x_turn_yacht_id', '=', id_boat_int), ('embarcacion_id', '=', id_boat_int)]

            if booking_exact:
                domain += [('name', '=', str(booking_exact))]
            elif booking_ilike:
                domain += [('name', 'ilike', booking_ilike)]

            if customer_q:
                domain += [('partner_id.name', 'ilike', customer_q)]

            Order = request.env['sale.order'].sudo()
            fields_order = [
                'name', 'partner_id', 'state', 'x_schedule_state',
                'embarcacion_id', 'x_turn_yacht_id',
                'rental_start_date', 'rental_return_date',
                'x_turn_date',  # por si el pedido es por turno
                'amount_total',
                'order_line',
            ]
            orders = Order.search_read(domain, fields_order, order='rental_start_date asc, id asc', limit=limit)

            if not orders:
                return request.make_response(
                    json.dumps({"results": []}, default=str),
                    headers=[('Content-Type','application/json')], status=200
                )

            # ---- 3) Periodos activos y bloqueos (igual que tu otra API) ----
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

            # ---- 4) Prefetch líneas (para Activity Name) ----
            order_ids = [o['id'] for o in orders]
            Line = request.env['sale.order.line'].sudo()
            fields_line = ['order_id', 'display_type', 'product_id', 'sequence', 'is_rental']
            lines = Line.search_read(
                [('order_id', 'in', order_ids), ('display_type', '=', False), ('product_id', '!=', False)],
                fields_line, order='sequence asc, id asc'
            )

            lines_by_order = defaultdict(list)
            for ln in lines:
                lines_by_order[ln['order_id'][0]].append(ln)

            # ---- 4.1) Determinar el producto elegido por pedido ----
            chosen_variant_by_order = {}
            variant_ids = set()
            for o in orders:
                cand = lines_by_order.get(o['id'], [])
                prefer = [ln for ln in cand if ln.get('is_rental')]
                pick = (prefer[0] if prefer else (cand[0] if cand else None))
                if pick and pick.get('product_id'):
                    pid = pick['product_id'][0]
                    chosen_variant_by_order[o['id']] = pid
                    variant_ids.add(pid)

            # ---- 4.2) Prefetch templates y taxes para esos productos ----
            ProductProduct = request.env['product.product'].sudo()
            ProductTemplate = request.env['product.template'].sudo()
            AccountTax = request.env['account.tax'].sudo()

            tmpl_by_variant = {}
            if variant_ids:
                variants = ProductProduct.search_read(
                    [('id', 'in', list(variant_ids))],
                    ['product_tmpl_id']
                )
                for v in variants:
                    if v.get('product_tmpl_id'):
                        tmpl_by_variant[v['id']] = v['product_tmpl_id'][0]

            tmpl_ids = list(set(tmpl_by_variant.values()))
            tmpl_data = {}
            tax_ids_all = set()
            if tmpl_ids:
                tpls = ProductTemplate.search_read(
                    [('id', 'in', tmpl_ids)],
                    [
                        'type', 'invoice_policy', 'list_price', 'standard_price',
                        'taxes_id', 'categ_id'
                    ]
                )
                for t in tpls:
                    tmpl_data[t['id']] = t
                    for tid in (t.get('taxes_id') or []):
                        tax_ids_all.add(tid)

            tax_name_by_id = {}
            if tax_ids_all:
                taxes = AccountTax.search_read([('id', 'in', list(tax_ids_all))], ['name', 'amount', 'type_tax_use'])
                for tx in taxes:
                    tax_name_by_id[tx['id']] = tx.get('name') or (str(tx.get('amount') or ''))

            # ---- 4.3) Prefetch detalles de barcos ----
            Vehicle = request.env['fleet.vehicle'].sudo()
            vehicle_fields = [
                'license_plate', 'category_id', 'acquisition_date', 'vin_sn',
                'odometer', 'odometer_unit', 'location', 'acquisition_price',
                'navigation_zone_id', 'general_state', 'model_economic_id',
                'propietario_actual_id', 'fecha_inicio_propiedad', 'tipo_propiedad',
                'distribuidor_actual_id'
            ]
            vehicles = {}
            if boat_ids:
                for v in Vehicle.search_read([('id', 'in', boat_ids)], vehicle_fields):
                    vehicles[v['id']] = v

            # para labels de selections
            vehicle_model = request.env['fleet.vehicle']

            # ---- 5) Construcción + filtros de estado + disponibilidad/bloqueos ----
            out = []
            today_loc = _today_local_date(tzname)

            for o in orders:
                # estado UI
                ui_state = None
                if o.get('x_schedule_state'):
                    ui_state = _norm_schedule_state(o['x_schedule_state'])
                if not ui_state:
                    tech = (o.get('state') or '').strip()
                    ui_state = self.TECH2UI.get(tech, tech)

                # filtrar por estados si pidieron
                if states_q:
                    if ui_state not in self.ALLOWED_UI_STATES or ui_state not in states_q:
                        continue

                # barco y periodos/bloqueos
                boat_tuple = o.get('x_turn_yacht_id') or o.get('embarcacion_id')
                if not boat_tuple:
                    continue
                bid, bname = boat_tuple[0], boat_tuple[1] or ""
                per_list  = periods_by_boat.get(bid, ())
                if not per_list:
                    continue  # sin periodos activos => fuera
                lock_list = locks_by_boat.get(bid, ())

                x_turn_date = o.get('x_turn_date')
                if x_turn_date:
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
                else:
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

                # boarding (solo fecha local)
                boarding = _utc_str_to_local_date_str(o.get('rental_start_date'), tzname)

                # activity name + detalles de producto
                activity_name = ""
                product_block = {}
                pid_variant = chosen_variant_by_order.get(o['id'])
                if pid_variant:
                    tmpl_id = tmpl_by_variant.get(pid_variant)
                    t = tmpl_data.get(tmpl_id) if tmpl_id else None

                    # activity_name
                    cand = lines_by_order.get(o['id'], [])
                    prefer = [ln for ln in cand if ln.get('is_rental')]
                    pick = (prefer[0] if prefer else (cand[0] if cand else None))
                    if pick and pick.get('product_id'):
                        activity_name = pick['product_id'][1] or ""

                    if t:
                        taxes_names = [tax_name_by_id.get(i, "") for i in (t.get('taxes_id') or [])]
                        taxes_str = ", ".join([n for n in taxes_names if n]) if taxes_names else ""
                        product_block = {
                            "id": int(tmpl_id),
                            "type": t.get('type') or "",
                            "invoice_policy": t.get('invoice_policy') or "",
                            "list_price": float(t.get('list_price') or 0.0),
                            "standard_price": float(t.get('standard_price') or 0.0),
                            "taxes_id": taxes_str,
                            "categ_id": (t.get('categ_id')[1] if t.get('categ_id') else "")
                        }

                # detalles del barco (fleet.vehicle)
                boat_block = {}
                v = vehicles.get(bid)
                if v:
                    boat_block = {
                        "id": int(bid),
                        "license_plate": v.get('license_plate') or "",
                        "category_id": (v.get('category_id')[1] if v.get('category_id') else ""),
                        "acquisition_date": v.get('acquisition_date') or "",
                        "vin_sn": v.get('vin_sn') or "",
                        "odometer": float(v.get('odometer') or 0.0),
                        "odometer_unit": _odo_unit_short(v.get('odometer_unit')),
                        "location": v.get('location') or "",
                        "acquisition_price": float(v.get('acquisition_price') or 0.0),
                        "navigation_zone_id": (v.get('navigation_zone_id')[1] if v.get('navigation_zone_id') else ""),
                        "general_state": _sel_label(vehicle_model, 'general_state', v.get('general_state')),
                        "model_economic_id": (v.get('model_economic_id')[1] if v.get('model_economic_id') else ""),
                        "propietario_actual_id": (v.get('propietario_actual_id')[1] if v.get('propietario_actual_id') else ""),
                        "fecha_inicio_propiedad": v.get('fecha_inicio_propiedad') or "",
                        "tipo_propiedad": _sel_label(vehicle_model, 'tipo_propiedad', v.get('tipo_propiedad')),
                        "distribuidor_actual_id": (v.get('distribuidor_actual_id')[1] if v.get('distribuidor_actual_id') else "")
                    }

                # income + profit_pct fijo
                income = float(o.get('amount_total') or 0.0)
                profit_pct = 0

                out.append({
                    "booking_number": o['name'],
                    "customer": o['partner_id'][1] if o.get('partner_id') else "",
                    "boarding": boarding,
                    "activity_name": activity_name,
                    "income": income,
                    "profit_pct": profit_pct,
                    "state": ui_state,
                    "boat_name": bname,
                    "product": product_block,
                    "boat": boat_block,
                })

            # ---- 6) Orden final: boarding, estado (prioridad), boat, booking
            state_idx = self.STATE_ORDER
            out.sort(key=lambda r: (
                r.get('boarding') or '',
                state_idx.get(r.get('state'), 99),
                r.get('boat_name') or '',
                r.get('booking_number') or ''
            ))

            return request.make_response(
                json.dumps({"results": out}, default=str),
                headers=[('Content-Type','application/json')], status=200
            )
        except Exception as e:
            _logger.exception("Crash en /api/bookings/list")
            return request.make_response(
                json.dumps({
                    "error": "internal_error",
                    "detail": str(e),
                    "traceback": traceback.format_exc().splitlines()[-20:]
                }, default=str),
                headers=[('Content-Type','application/json')], status=500
            )
