/** @odoo-module **/

import { Component, onMounted, onWillUnmount, onWillStart, onWillUpdateProps, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { loadJS, loadCSS } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";

const SELECT_COLOR = "#875A7B";
const HIGHLIGHT_COLOR = "rgba(135, 90, 123, 0.18)";
const GREEN = "#4CAF50";
const BUSY_BG = "#ffeeee";
const DISABLED_BG = "#f5f5f5";

class RangePlannerField extends Component {
  static template = "custom_rental.RangePlannerField";
  static props = { ...standardFieldProps };
  static supportedTypes = ["char", "text"];

  setup() {
    this.orm = useService("orm");
    this.calRef = useRef("calendar");
    this.inputRef = useRef("input");

    this.calendar = null;
    this.selected = new Set();
    this.preselected = new Set();
    this.busy = new Set();
    this.allowedStart = null;
    this.allowedEnd = null;

    this._drag = { active: false, start: null, moved: false };

    // -------- utils --------
    this.parseCSV = (txt) => (txt || "").split(",").map((s) => s.trim()).filter(Boolean);

    this.fmt = (v) => {
      if (!v) return "";
      if (typeof v === "string") {
        const m = v.match(/^(\d{4})-(\d{2})-(\d{2})/);
        if (m) return m[0];
        const d = new Date(v);
        return isNaN(d) ? "" : d.toISOString().slice(0, 10);
      }
      if (v instanceof Date) return v.toISOString().slice(0, 10);
      if (typeof v === "object") {
        if (Number.isInteger(v.year) && Number.isInteger(v.month) && Number.isInteger(v.day)) {
          const mm = String(v.month).padStart(2, "0");
          const dd = String(v.day).padStart(2, "0");
          return `${v.year}-${mm}-${dd}`;
        }
        if (typeof v.toISOString === "function") return v.toISOString().slice(0, 10);
        try { const d = new Date(v); return isNaN(d) ? "" : d.toISOString().slice(0, 10); } catch { return ""; }
      }
      return "";
    };

    this.todayISO = () => this.fmt(new Date());
    this.addDaysISO = (val, n) => {
      const s = this.fmt(val); if (!s) return "";
      const [y,m,d] = s.split("-").map(Number);
      const dt = new Date(y, m-1, d); dt.setHours(12,0,0,0); dt.setDate(dt.getDate()+n);
      return dt.toISOString().slice(0,10);
    };

    this.inSeason = (iso) => !!iso && !!this.allowedStart && !!this.allowedEnd && iso >= this.allowedStart && iso <= this.allowedEnd;
    this.isDisabledISO = (iso) => !this.inSeason(iso) || this.busy.has(iso);
    this.toCSV = () => Array.from(new Set([...this.preselected, ...this.selected])).sort().join(", ");

    this._commitValue = () => {
      const val = this.toCSV();
      if (this.inputRef.el) {
        this.inputRef.el.value = val;
        this.inputRef.el.dispatchEvent(new Event("input", { bubbles: true }));
        this.inputRef.el.dispatchEvent(new Event("change", { bubbles: true }));
      }
      if (typeof this.props.update === "function") this.props.update(val);
      else if (this.props.record && this.props.name) this.props.record.update({ [this.props.name]: val });
    };

    this.toggleDay = (iso) => {
      if (this.isDisabledISO(iso)) return false;
      if (this.preselected.has(iso)) { this.preselected.delete(iso); this.selected.delete(iso); }
      else if (this.selected.has(iso)) { this.selected.delete(iso); }
      else { this.selected.add(iso); }
      return true;
    };

    this.repaint = () => {
      if (!this.calRef.el) return;
      const cells = this.calRef.el.querySelectorAll(".fc-daygrid-day");
      cells.forEach((cell) => {
        const iso = cell.getAttribute("data-date");
        cell.classList.remove("rp-out","rp-busy","rp-pre","rp-sel","rp-clickable","rp-drag");
        const out = !this.inSeason(iso);
        const busy = this.busy.has(iso);
        const isPre = this.preselected.has(iso);
        const isSel = this.selected.has(iso);
        if (out) cell.classList.add("rp-out");
        else if (busy) cell.classList.add("rp-busy");
        else {
          if (isPre) cell.classList.add("rp-pre");
          if (isSel) cell.classList.add("rp-sel");
          cell.classList.add("rp-clickable");
        }
      });
    };

    // -------- lifecycle --------
    onWillStart(async () => {
      await loadCSS("/custom_rental/static/src/lib/fullcalendar/main.min.css");
      await loadJS("/custom_rental/static/src/lib/fullcalendar/index.global.min.js");
    });

    onWillUpdateProps((next) => {
      this.allowedStart = this.fmt(next?.record?.data?.allowed_start_date || null) || null;
      this.allowedEnd   = this.fmt(next?.record?.data?.allowed_end_date   || null) || null;

      this.preselected = new Set(this.parseCSV(next.value).map(this.fmt).filter((d) => d && this.inSeason(d)));
      this.selected = new Set();

      try { this.busy = new Set(JSON.parse(next?.record?.data?.disabled_dates_json || "[]")); } catch { this.busy = new Set(); }

      this._commitValue();

      if (this.calendar) {
        if (this.allowedStart && this.allowedEnd) this.calendar.changeView("multiMonthYear", this.allowedStart);
        setTimeout(() => this.repaint(), 0);
      }
    });

    onMounted(() => {
      const calEl = this.calRef.el; if (!calEl) return;
      const FC = window.FullCalendar; if (!FC?.Calendar) return;

      this.allowedStart = this.fmt(this.props?.record?.data?.allowed_start_date || null) || null;
      this.allowedEnd   = this.fmt(this.props?.record?.data?.allowed_end_date   || null) || null;

      this.preselected = new Set(); this.selected = new Set();
      try { this.busy = new Set(JSON.parse(this.props?.record?.data?.disabled_dates_json || "[]")); } catch { this.busy = new Set(); }

      const targetISO = (this.allowedStart && this.allowedEnd) ? this.allowedStart : this.todayISO();

      this.calendar = new FC.Calendar(calEl, {
        timeZone: "local",
        initialDate: targetISO,
        initialView: "multiMonthYear",
        multiMonthMaxColumns: 3,
        multiMonthMinWidth: 260,
        locale: "es",
        selectable: false,            // sin selección nativa
        unselectAuto: false,
        selectMirror: false,
        dayMaxEvents: true,
        eventInteractive: false,
        headerToolbar: { left: "prev,next today", center: "title", right: "multiMonthYear,dayGridMonth" },
        views: { multiMonthYear: { type: "multiMonth", duration: { months: 3 } } },
        dayCellDidMount: () => {},
        dayCellWillUnmount: () => {},
        datesSet: () => setTimeout(() => this.repaint(), 0), // repintar al navegar
      });

      // estilos
      const styleId = "range-planner-styles";
      if (!document.getElementById(styleId)) {
        const style = document.createElement("style");
        style.id = styleId;
        style.textContent = `
          .fc-multimonth { gap: 16px; }
          .fc-multimonth-month {
            background: #fff;
            border: 1px solid rgba(0,0,0,.06);
            border-radius: 12px;
            padding: 8px 10px 12px;
            box-shadow: 0 1px 2px rgba(0,0,0,.03);
          }
          .fc-multimonth-month-title { margin: 4px 8px 8px; font-weight: 600; }
          .fc .fc-daygrid-day { min-height: 34px; }

          .rp-out .fc-daygrid-day-frame { background: ${DISABLED_BG} !important; opacity: .55; pointer-events: none; }
          .rp-busy .fc-daygrid-day-frame { background: ${BUSY_BG} !important; pointer-events: none; }
          .rp-pre .fc-daygrid-day-frame { background: ${GREEN}22 !important; border: 1px dashed ${GREEN}; border-radius: 10px; }
          .rp-sel .fc-daygrid-day-frame { background: ${SELECT_COLOR}26 !important; border: 2px solid ${SELECT_COLOR}; border-radius: 10px; }

          .rp-clickable { cursor: pointer; }
          .rp-clickable:hover .fc-daygrid-day-frame { box-shadow: inset 0 0 0 2px ${SELECT_COLOR}; border-radius: 10px; }
          .rp-drag .fc-daygrid-day-frame { box-shadow: inset 0 0 0 2px ${SELECT_COLOR}; border-radius: 10px; }
        `;
        document.head.appendChild(style);
      }

      this.calRef.el.style.setProperty("--fc-highlight-color", HIGHLIGHT_COLOR);
      this.calendar.render();
      this.calendar.changeView("multiMonthYear", targetISO);

      this.repaint();
      this._commitValue();

      // --- Interacción propia ---
      const onMouseDown = (ev) => {
        const cell = ev.target.closest(".fc-daygrid-day.rp-clickable");
        if (!cell) return;
        const iso = cell.getAttribute("data-date");
        if (this.isDisabledISO(iso)) return;
        this._drag = { active: true, start: iso, moved: false };
        ev.preventDefault();
        cell.classList.add("rp-drag");
      };

      const onMouseEnter = (ev) => {
        if (!this._drag.active) return;
        const cell = ev.target.closest(".fc-daygrid-day"); if (!cell) return;
        const overIso = cell.getAttribute("data-date");
        this._drag.moved = true;
        this.calRef.el.querySelectorAll(".rp-drag").forEach((el) => el.classList.remove("rp-drag"));
        if (this._drag.start && overIso) {
          let a = this._drag.start, b = overIso;
          if (a > b) [a, b] = [b, a];
          let cur = a;
          while (cur && cur <= b) {
            const el = this.calRef.el.querySelector(`.fc-daygrid-day[data-date="${cur}"]`);
            if (el && !this.isDisabledISO(cur)) el.classList.add("rp-drag");
            cur = this.addDaysISO(cur, 1);
          }
        }
      };

      const onMouseUp = (ev) => {
        if (!this._drag.active) return;
        const cell = ev.target.closest(".fc-daygrid-day");
        const upIso = (cell && cell.getAttribute("data-date")) || this._drag.start;

        this.calRef.el.querySelectorAll(".rp-drag").forEach((el) => el.classList.remove("rp-drag"));
        const { start, moved } = this._drag;
        this._drag = { active: false, start: null, moved: false };
        if (!start) return;

        if (!moved) {
          if (!this.isDisabledISO(upIso) && this.toggleDay(upIso)) { this._commitValue(); this.repaint(); }
          return;
        }

        let a = start, b = upIso; if (a > b) [a, b] = [b, a];
        let changed = false, cur = a;
        while (cur && cur <= b) {
          if (!this.isDisabledISO(cur)) changed = this.toggleDay(cur) || changed;
          cur = this.addDaysISO(cur, 1);
        }
        if (changed) { this._commitValue(); this.repaint(); }
      };

      calEl.addEventListener("mousedown", onMouseDown);
      calEl.addEventListener("mouseenter", onMouseEnter, true);
      window.addEventListener("mouseup", onMouseUp);

      this._cleanup = () => {
        calEl.removeEventListener("mousedown", onMouseDown);
        calEl.removeEventListener("mouseenter", onMouseEnter, true);
        window.removeEventListener("mouseup", onMouseUp);
      };
    });

    onWillUnmount(() => {
      try { this._cleanup && this._cleanup(); } catch {}
      this.calendar?.destroy();
    });
  }
}

registry.category("fields").add("range_planner", { component: RangePlannerField });
export default RangePlannerField;
