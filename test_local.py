"""
test_local.py
Prueba el API con todos los PDFs localmente (sin levantar el servidor).

Uso:
    pip install pdfplumber flask
    python test_local.py                      # prueba todos los PDFs en ./pdfs/
    python test_local.py archivo.pdf          # prueba un PDF específico
    python test_local.py --server             # levanta el servidor en localhost:5000
"""

import sys, os, json, base64

# Agregar directorio actual al path
sys.path.insert(0, os.path.dirname(__file__))

def test_pdf(path):
    from app import _read_pdf, _is_plan_req, _parse

    name = os.path.basename(path)
    print(f"\n{'─'*65}")
    print(f"  📄 {name}")
    print('─'*65)

    with open(path, 'rb') as f:
        pdf_bytes = f.read()

    pages = _read_pdf(pdf_bytes)
    text  = '\n'.join(pages)

    if not _is_plan_req(text):
        print("  ⚠️  No reconocido como REQ de Plan International")
        return

    r = _parse(text, pages, name)
    h = r['header']

    print(f"  REQ#  : {h['RequisitionNumber']}")
    print(f"  Org   : {h['PurchaseOrganisation']}")
    print(f"  Grp   : {h['PurchaseGroup']}")
    print(f"  De    : {h['PreparedBy']}")
    print(f"  Aprob : {h['ApprovedBy']}")
    print(f"  Fecha : Creac {h['RequisitionCreationDate']}  Aprov {h['RequisitionApprovalDate']}")
    print(f"  DESC  : {h['REQDescription'][:70]}")
    print(f"  Total : {r['summary']['TotalValue']}   |   Ítems: {r['summary']['TotalItems']}")
    print()

    for it in r['items']:
        print(f"    [{it['SN']}] {it['Description'][:52]:<52} "
              f"{it['Quantity']:>10} {it['Currency']}  "
              f"Val: {it['Valuation']:<12}  "
              f"{it['DeliveryDate']}  GL:{it['GLAccount']}  {it['WBSElement']}")

    # Guardar JSON
    out = path.replace('.pdf', '_result.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(r, f, ensure_ascii=False, indent=2)
    print(f"\n  💾 JSON guardado → {out}")


def test_base64_roundtrip(path):
    """Simula exactamente lo que hace Power Automate: base64 → API → JSON"""
    from app import app
    import io

    name = os.path.basename(path)
    print(f"\n  🔄 Simulando llamada HTTP para: {name}")

    with open(path, 'rb') as f:
        pdf_b64 = base64.b64encode(f.read()).decode()

    with app.test_client() as client:
        resp = client.post('/extract',
            json={'filename': name, 'content': pdf_b64},
            content_type='application/json')

    data = resp.get_json()
    if resp.status_code == 200:
        print(f"  ✅ HTTP 200 — REQ#{data['header']['RequisitionNumber']} — {data['summary']['TotalItems']} ítems")
    else:
        print(f"  ❌ HTTP {resp.status_code} — {data.get('error')}")


if __name__ == '__main__':
    if '--server' in sys.argv:
        from app import app
        print("🚀 Servidor corriendo en http://localhost:5000")
        print("   Endpoint: POST http://localhost:5000/extract")
        print("   Health:   GET  http://localhost:5000/health")
        app.run(host='0.0.0.0', port=5000, debug=True)

    elif len(sys.argv) > 1 and not sys.argv[1].startswith('--'):
        path = sys.argv[1]
        test_pdf(path)
        test_base64_roundtrip(path)

    else:
        # Buscar PDFs en ./pdfs/ o en el directorio actual
        search_dirs = ['./pdfs', '.']
        pdfs = []
        for d in search_dirs:
            if os.path.isdir(d):
                pdfs += [os.path.join(d, f) for f in os.listdir(d) if f.endswith('.pdf')]
            if pdfs:
                break

        if not pdfs:
            print("No se encontraron PDFs. Uso: python test_local.py archivo.pdf")
            sys.exit(1)

        print(f"\n{'='*65}")
        print(f"  REQ Extractor — Prueba local ({len(pdfs)} PDFs)")
        print('='*65)

        ok = warn = 0
        for p in sorted(pdfs):
            try:
                test_pdf(p)
                ok += 1
            except Exception as e:
                print(f"  ❌ ERROR en {os.path.basename(p)}: {e}")
                warn += 1

        print(f"\n{'='*65}")
        print(f"  RESULTADO: ✅ {ok} OK   ❌ {warn} errores")
        print('='*65)
