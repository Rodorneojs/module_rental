# -*- coding: utf-8 -*-
from collections import defaultdict
from odoo import http
from odoo.http import request
from odoo.fields import Datetime, Date
from datetime import datetime as py_dt, date as py_date, time as py_time
import json
import logging

_logger = logging.getLogger(__name__)

# ─────────── Helpers ───────────
def _to_date(val):
    """Normaliza str/datetime/date -> date (o None)."""
    if not val:
        return None
    if isinstance(val, py_dt):      # datetime hereda de date → tratar primero
        return val.date()
    if isinstance(val, py_date):
        return val
    dt = Datetime.from_string(val)  # string Odoo → datetime
    return dt.date()

def _to_date_str(val):
    """YYYY-MM-DD (o '')."""
    d = _to_date(val)
    return Date.to_string(d) if d else ""

def _field_exists(model, name):
    IM = request.env['ir.model'].sudo()
    IMF = request.env['ir.model.fields'].sudo()
    m = IM.search([('model', '=', model)], limit=1)
    if not m:
        return False
    return bool(IMF.search_count([('model_id', '=', m.id), ('name', '=', name)]))

def _read_params(post):
    """Lee parámetros desde JSON (raw) o form-data/urlencoded (fallback)."""
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
    # Fallback: **post (form-data / x-www-form-urlencoded)
    return post


class RentalAPIController(http.Controller):
    """
    POST /api/boats/availability
    Body (JSON o form-data):
      {
        "id_boat": 1,                # opcional
        "fecha": "YYYY-MM-DD",       # opcional (equivale a rango de 1 día)
        "start": "YYYY-MM-DD",       # opcional
        "end": "YYYY-MM-DD"          # opcional
      }

    Respuesta: lista de objetos (un objeto por *pedido* válido).
    """

    @http.route('/api/boats/availability', type='http',
                auth='public', methods=['POST'], csrf=False)
    def boats_availability(self, **post):
        try:
            # ── Parámetros (acepta JSON o form-data)
            params      = _read_params(post)
            id_boat     = params.get('id_boat')
            fecha_param = params.get('fecha')     # compat: día único
            start_param = params.get('start')
            end_param   = params.get('end')

            # ── Rango solicitado → normalizado a date
            try:
                start_req = py_dt.strptime(start_param, "%Y-%m-%d").date() if start_param else None
                end_req   = py_dt.strptime(end_param,   "%Y-%m-%d").date() if end_param   else None
                if not (start_req and end_req) and fecha_param:
                    only = py_dt.strptime(fecha_param, "%Y-%m-%d").date()
                    start_req = end_req = only
            except ValueError:
                return request.make_response(
                    json.dumps({"error": "Formato inválido. Usa YYYY-MM-DD en 'start', 'end' o 'fecha'."}),
                    headers=[('Content-Type', 'application/json')], status=400
                )

            today = py_date.today()
            if start_req and (start_req < today or end_req < today or end_req < start_req):
                return request.make_response(
                    json.dumps({"error": "Rango inválido: no se permiten fechas pasadas ni end < start."}),
                    headers=[('Content-Type', 'application/json')], status=400
                )

            # ── Modelos
            Boat  = request.env['fleet.vehicle'].sudo()
            Avail = request.env['rental.availability'].sudo()
            Block = request.env['rental.blocked.period'].sudo()
            Order = request.env['sale.order'].sudo()
            Line  = request.env['sale.order.line'].sudo()

            # ── Barcos
            if id_boat is not None and id_boat != "":
                try:
                    boats = Boat.browse(int(id_boat))
                except Exception:
                    return request.make_response(
                        json.dumps({"error": "id_boat debe ser numérico"}),
                        headers=[('Content-Type', 'application/json')], status=400
                    )
            else:
                boats = Boat.search([], order="id ASC")

            if id_boat and not boats.exists():
                return request.make_response(
                    json.dumps({"error": "Barco no encontrado"}),
                    headers=[('Content-Type', 'application/json')], status=404
                )
            boat_ids = boats.ids
            if not boat_ids:
                return request.make_response(json.dumps([]),
                                             headers=[('Content-Type', 'application/json')], status=200)

            # ── Periodos disponibles (activos) → date
            periods = Avail.search_read(
                [('boat_id', 'in', boat_ids), ('state', '=', 'active')],
                ['boat_id', 'date_from', 'date_to']
            )
            periods_by_boat = defaultdict(list)
            for p in periods:
                bid = p['boat_id'][0]
                d1  = _to_date(p['date_from'])
                d2  = _to_date(p['date_to'])
                if d1 and d2:
                    periods_by_boat[bid].append((d1, d2))

            # ── Bloqueos (un día) → date
            locks = Block.search_read(
                [('boat_id', 'in', boat_ids)],
                ['boat_id', 'date_blocked', 'block_type']
            )
            locks_by_boat = defaultdict(list)
            for b in locks:
                bid = b['boat_id'][0]
                d   = _to_date(b['date_blocked'])
                if d:
                    locks_by_boat[bid].append((d, d, b['block_type']))

            # ── Traer TODAS las cotizaciones relevantes (state=draft)
            order_domain = [('embarcacion_id', 'in', boat_ids),
                            ('state', '=', 'draft')]
            if start_req and end_req:
                # Pedidos cuyo rango esté DENTRO del rango solicitado
                start_dt = Datetime.to_string(py_dt.combine(start_req, py_time.min))
                end_dt   = Datetime.to_string(py_dt.combine(end_req,   py_time.max))
                order_domain += [
                    ('rental_start_date', '>=', start_dt),
                    ('rental_return_date', '<=', end_dt),
                ]
                order_order = 'embarcacion_id ASC, rental_start_date ASC, id ASC'
            else:
                # ⬅⬅ CAMBIO: incluir pedidos vigentes o futuros (fin >= hoy)
                today_dt = Datetime.to_string(py_dt.combine(today, py_time.min))
                order_domain += [('rental_return_date', '>=', today_dt)]
                order_order = 'embarcacion_id ASC, rental_start_date ASC, id ASC'

            orders = Order.search_read(
                order_domain,
                ['id', 'embarcacion_id', 'rental_start_date', 'rental_return_date'],
                order=order_order
            )

            # Líneas de esos pedidos
            order_ids = [o['id'] for o in orders]
            lines_by_order = defaultdict(list)
            if order_ids:
                olines = Line.search_read(
                    [('order_id', 'in', order_ids)],
                    ['order_id', 'product_id', 'product_uom_qty']
                )
                for l in olines:
                    lines_by_order[l['order_id'][0]].append(l)

            # ── Construir respuesta: UN OBJETO POR PEDIDO VÁLIDO
            result = []
            for o in orders:
                bid = o['embarcacion_id'][0] if o['embarcacion_id'] else None
                if not bid:
                    continue

                o_start = _to_date(o.get('rental_start_date'))
                o_end   = _to_date(o.get('rental_return_date'))
                if not o_start or not o_end or o_end < today:
                    continue

                # Inclusión estricta dentro de una disponibilidad activa del barco
                if not any(p_start <= o_start and p_end >= o_end
                           for (p_start, p_end) in periods_by_boat.get(bid, [])):
                    continue

                # Si hay un bloqueo que se cruza con el rango del pedido → descartar
                if any(l_start <= o_end and l_end >= o_start
                       for (l_start, l_end, _t) in locks_by_boat.get(bid, [])):
                    continue

                # Actividad y cuota (primera línea del pedido)
                first_line = (lines_by_order.get(o['id'], []) or [None])[0]

                # Bloqueos futuros informativos del barco (no solo del rango)
                bloqueos_payload = [{
                    "fecha_ini": _to_date_str(l_start),
                    "fecha_fin": _to_date_str(l_end),
                    "tipo": "privado" if t == 'private' else "mantenimiento",
                } for (l_start, l_end, t) in locks_by_boat.get(bid, []) if l_end >= today]

                # Un objeto por pedido:
                result.append({
                    "id_boat": bid,
                    "disponibilidad": [{
                        "id_actividad": (first_line['product_id'][0] if first_line and first_line.get('product_id') else ""),
                        "quota": (first_line['product_uom_qty'] if first_line else 0),
                        "periodos": [{
                            "fecha_ini": _to_date_str(o_start),
                            "fecha_fin": _to_date_str(o_end),
                        }],
                        "bloqueos": bloqueos_payload
                    }]
                })

            # ── Orden final (por si el order del search_read cambia)
            def _sort_key(item):
                bid = item.get('id_boat') or 0
                try:
                    finicio = item['disponibilidad'][0]['periodos'][0]['fecha_ini'] or ''
                except Exception:
                    finicio = ''
                return (bid, finicio)

            result.sort(key=_sort_key)

            return request.make_response(
                json.dumps(result),
                headers=[('Content-Type', 'application/json')], status=200
            )

        except Exception as e:
            _logger.exception("API /api/boats/availability failed")
            return request.make_response(
                json.dumps({"error": "Internal error", "detail": str(e)}),
                headers=[('Content-Type', 'application/json')], status=500
            )
