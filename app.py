"""
REQ Extractor API — Plan International
Extrae datos de Requisiciones SAP desde PDF en base64.
Compatible con PDFs de Paraguay, República Dominicana y Perú.
"""

import re, io, base64, logging,json
from datetime import datetime, timezone
from flask import Flask, request, jsonify
import pdfplumber


logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

app = Flask(__name__)


# ─── ENDPOINTS ────────────────────────────────────────────────────────────────

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'ok',
        'service': 'REQ Extractor API - Plan International',
        'version': '1.0.0',
        'timestamp': datetime.now(timezone.utc).isoformat()
    })


@app.route('/extract', methods=['POST'])
def extract():
    """
    POST /extract
    Body JSON:  { "filename": "...", "content": "<base64 del PDF>" }
    Respuesta:  { "header": {...}, "items": [...], "summary": {...} }
    """
    if not request.is_json:
        return jsonify({'error': 'Content-Type debe ser application/json'}), 400

    body     = request.get_json(silent=True) or {}
    pdf_b64  = body.get('content') or ''
    filename = body.get('filename') or 'document.pdf'

    if not pdf_b64:
        return jsonify({'error': 'Campo requerido: "content" (PDF en base64)'}), 400

    # Decodificar base64
    try:
        if ',' in pdf_b64:                          # quitar prefijo data URI si existe
            pdf_b64 = pdf_b64.split(',', 1)[1]
        pdf_bytes = base64.b64decode(pdf_b64.replace(' ', '').replace('\n', ''))
    except Exception as e:
        return jsonify({'error': f'base64 inválido: {e}'}), 400

    log.info(f"Procesando: {filename} ({len(pdf_bytes):,} bytes)")

    # Leer PDF
    try:
        pages = _read_pdf(pdf_bytes)
    except Exception as e:
        return jsonify({'error': f'No se pudo leer el PDF: {e}'}), 422

    full_text = '\n'.join(pages)

    if len(full_text.strip()) < 50:
        return jsonify({'error': 'PDF basado en imágenes (escaneado). Solo se procesan PDFs digitales de SAP.'}), 422

    if not _is_plan_req(full_text):
        return jsonify({'error': 'No es una Requisición de Plan International.'}), 422

    result = _parse(full_text, pages, filename)
    log.info(f"✅ REQ#{result['header']['RequisitionNumber']} — {result['summary']['TotalItems']} ítems")
    return jsonify(result), 200


# ─── PDF READING ──────────────────────────────────────────────────────────────

def _read_pdf(pdf_bytes):
    pages = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            # layout=True preserva posición horizontal → ítems quedan en una línea
            text = page.extract_text(layout=True) or page.extract_text() or ''
            pages.append(text)
    return pages

def _is_plan_req(text):
    u = text.upper()
    return 'PLAN' in u and 'INTERNATIONAL' in u and 'REQUISITION' in u


# ─── HEADER PARSING ───────────────────────────────────────────────────────────

def _field(text, labels, max_len=150):
    """Devuelve el valor que sigue a la primera etiqueta encontrada."""
    for label in labels:
        idx = text.find(label)
        if idx == -1:
            idx = text.lower().find(label.lower())
        if idx == -1:
            continue
        after = text[idx + len(label):].lstrip(' \t')
        for line in after.split('\n'):
            val = line.strip()[:max_len]
            if val:
                return val
    return ''

def _date(text, labels):
    raw = _field(text, labels, 50)
    m = re.search(r'\d{2}[./]\d{2}[./]\d{4}', raw)
    return m.group(0) if m else raw[:12].strip()


# ─── ITEM PARSING ─────────────────────────────────────────────────────────────

# Formato real de una línea de ítem (basado en PDFs reales de SAP Plan International):
#
#  Paraguay:  00010 P  1038   Jugo en botella de 250 C/U 450.000 PYG 1,012,500 06.02.2026 666070 PRJPY4047 PY02160-...
#  Perú:      00010 K  1037   AWS - Server RIE  C/U 1.000 USD  494.33 25.07.2025 668050 SPCPE6084
#  Rep.Dom:   00010 P  03030  Contratación Agencia DI C/U 1,000 DOP 3.700.000,0011.12.2025 641090 FNDDODO DO04427-...
#                                                                              ↑ sin espacio entre valoración y fecha (DOM)

ITEM_RE = re.compile(
    r'^\s*'
    r'(\d{5})\s+'                                           # SN         00010
    r'([A-Z])\s+'                                           # AcctCat    P / K
    r'(\d+)\s+'                                             # MatGroup   1038
    r'(.*?)\s+'                                             # Desc       texto variable
    r'(C/U|EA|C/S|KG|LT|MT|UN|HRS?|DÍAS?|M2|ML)\s+'        # Unit       C/U, EA…
    r'([\d.,]+)\s+'                                         # Quantity   450.000
    r'(DOP|PYG|USD|EUR|PEN|CLP|GBP|COP|BOB|UYU)\s*'        # Currency   PYG, DOP… (espacio opcional → DOM)
    r'([\d.,]+)',                                           # Valuation  1,012,500
    re.IGNORECASE
)

# Continúa buscando fecha, GL, CostCenter, WBS después de la valoración
TAIL_RE = re.compile(
    r'(\d{2}\.\d{2}\.\d{4})\s+'    # DeliveryDate
    r'(\d{6})\s+'                   # GLAccount
    r'(\S+)'                        # CostCenter
    r'(?:\s+(\S+))?'                # WBSElement (opcional)
)

def _parse_items(text):
    items = []
    lines = text.split('\n')

    for i, line in enumerate(lines):
        m = ITEM_RE.match(line)
        if not m:
            continue

        sn          = m.group(1)
        acct_cat    = m.group(2)
        mat_grp     = m.group(3)
        desc_part1  = m.group(4).strip()
        unit        = m.group(5).upper()
        quantity    = m.group(6)
        currency    = m.group(7).upper()
        valuation   = m.group(8)

        # Lo que queda después de la valoración en la misma línea
        tail = line[m.end():].strip()

        # En Rep. Dom, la fecha está pegada a la valoración sin espacio
        # Buscamos la fecha en la cola, o al final de la valoración si no hay espacio
        deliv_date = gl_account = cost_center = wbs = ''

        # ── Leer la línea de continuación (raw, con espacios) ──────────────────
        # La usamos para detectar sufijo del Cost Center por posición de columna
        next_line_raw = lines[i + 1] if i + 1 < len(lines) else ''
        next_line     = next_line_raw.strip()

        # ── Parsear cola (fecha, GL, CostCenter, WBS) ────────────────────────
        t = TAIL_RE.search(tail)
        if t:
            deliv_date   = t.group(1)
            gl_account   = t.group(2)
            cost_center  = t.group(3)
            wbs          = t.group(4) or ''
        else:
            # Caso DOM: fecha pegada a valoración sin espacio → buscar en línea completa
            date_m = re.search(r'(\d{2}\.\d{2}\.\d{4})', line[m.end(7):])
            if date_m:
                deliv_date = date_m.group(1)
                rest = line[line.find(deliv_date) + 10:].strip()
                gl_m = re.search(r'(\d{6})', rest)
                if gl_m:
                    gl_account = gl_m.group(1)
                    after_gl = rest[gl_m.end():].strip().split()
                    cost_center = after_gl[0] if after_gl else ''
                    wbs = after_gl[1] if len(after_gl) > 1 else ''

        # ── Detectar sufijo del Cost Center en la línea de continuación ──────
        # SAP a veces parte el Cost Center en dos líneas (ej: PRJDODOM + 1 = PRJDODOM1)
        # El sufijo aparece en la misma columna horizontal que el Cost Center en l1,
        # es decir: a la derecha de la zona de descripción (col ~65+) y antes del WBS.
        # Estrategia: buscar el CC en la línea principal, tomar su columna,
        # y extraer lo que haya en esa zona en la línea de continuación.
        cc_suffix = ''
        desc_extra = ''

        is_continuation = (
            next_line
            and not next_line.startswith('ITEM TEXT')
            and not ITEM_RE.match(next_line_raw)
            and not next_line.startswith('Total Value')
            and not next_line.startswith('S/N')
        )

        if is_continuation and cost_center and next_line_raw:
            # Buscar el sufijo del CC en el rango entre descripción y WBS en la línea de continuación.
            # SAP parte "PRJDODOM1" → "PRJDODOM" (línea 1) + "1" (línea 2, misma col o cerca)
            # y "FNDDODOM1" → "FNDDODO" + "M1" (puede estar antes del CC por formato DOM)
            # Estrategia: el sufijo está en el rango [desc_end … wbs_col] de la línea cont.
            desc_end_col = 65   # la descripción siempre termina antes de la col 65
            wbs_col = -1
            if wbs:
                wbs_col = line.find(wbs)
            if wbs_col == -1:
                # Si WBS no estaba en la línea principal buscar patrón WBS en cont.
                wbs_m2 = re.search(r'[A-Z]{2}\d{5}', next_line_raw)
                wbs_col = wbs_m2.start() if wbs_m2 else len(next_line_raw)

            zone = next_line_raw[desc_end_col:wbs_col].strip()
            # Es sufijo si: corto (≤6 chars), alfanumérico, sin espacios internos
            if zone and len(zone) <= 6 and re.match(r'^[A-Z0-9]+$', zone, re.IGNORECASE):
                cc_suffix = zone
                desc_extra = next_line_raw[:desc_end_col].strip()
            else:
                desc_extra = next_line

        elif is_continuation:
            desc_extra = next_line

        # Concatenar sufijo al Cost Center
        if cc_suffix:
            cost_center = cost_center + cc_suffix

        # WBS puede estar en la siguiente línea en DOM si no se encontró arriba
        if not wbs and desc_extra:
            parts = desc_extra.split()
            if parts and re.match(r'^[A-Z]{2}\d{5}', parts[0]):
                wbs = parts[0]
                desc_extra = ''

        full_desc = (desc_part1 + ' ' + desc_extra).strip()

        items.append({
            'SN':                        sn,
            'AccountAssignmentCategory': acct_cat,
            'MaterialGroup':             mat_grp,
            'Description':               full_desc[:300],
            'Unit':                      unit,
            'Quantity':                  quantity,
            'Currency':                  currency,
            'Valuation':                 valuation,
            'DeliveryDate':              deliv_date,
            'GLAccount':                 gl_account,
            'CostCenter':                cost_center,
            'WBSElement':                wbs,
        })

    return items


# ─── OBSERVATIONS ───────────────────────────────────────────────────────────────
def _get_observations(full_text):
    """
    Extrae observaciones/anotaciones libres escritas por el usuario,
    que aparecen en el bloque inferior del PDF despues del Total Value.
    Devuelve string con las lineas unidas por newline, o "" si no hay ninguna.
    """
    matches = list(re.finditer(r'Total\s+Value', full_text, re.IGNORECASE))
    if not matches:
        return ''

    after = full_text[matches[-1].end():]

    obs_lines = []
    for line in after.split('\n'):
        stripped = line.strip()
        if not stripped:
            continue
        # Ignorar lineas que son solo numeros (valor del total partido en 2 lineas, caso DOM)
        if re.match(r'^[\d.,\s:]+$', stripped):
            continue
        obs_lines.append(stripped)

    return '\n'.join(obs_lines)


def _parse(full_text, pages, filename):
    h = {
        'PurchaseOrganisation':    _field(full_text, ['Purchase Organisation', 'Purchase Organization']),
        'PurchaseGroup':           _field(full_text, ['Purchase Group']),
        'RequisitionNumber':       _field(full_text, ['Requisition #', 'Requisition#'], 20),
        'PreparedBy':              _field(full_text, ['Prepared/Submitted By', 'Prepared By']),
        'ApprovedBy':              _field(full_text, ['Approved By']),
        'RequisitionCreationDate': _date(full_text,  ['Requisition Creation Date']),
        'RequisitionApprovalDate': _date(full_text,  ['Requisition Approval Date']),
        'RunDate':                 _date(full_text,  ['Run Date']),
        'PrintedBy':               _field(full_text, ['Printed By'], 40),
        'REQDescription':          _field(full_text, ['REQ Description :', 'REQ Description:'], 500),
    }
    items = _parse_items(full_text)
    total_m = re.search(r'Total\s+Value\s*:?\s*\n?\s*([\d.,]+)', full_text, re.IGNORECASE)

    return {
        'metadata': {
            'extractedAt': datetime.now(timezone.utc).isoformat(),
            'source':      'REQ Extractor API v1.0 - Plan International',
            'filename':    filename,
            'pagesCount':  len(pages),
        },
        'header':  h,
        # 'items':   items,
        'items':   json.dumps(items),
        'summary': {
            'TotalValue':   total_m.group(1) if total_m else '',
            'TotalItems':   len(items),
            'Observations': _get_observations(full_text),
        }
    }


# ─── RUN ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    log.info(f"🚀 REQ Extractor API → http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, debug=True)
