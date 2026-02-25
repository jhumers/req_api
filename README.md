# REQ Extractor API — Plan International

API en Python/Flask que extrae datos de Requisiciones SAP desde PDF en base64.

---

## PASO 1 — PROBAR LOCALMENTE

### Instalar dependencias
```bash
pip install -r requirements.txt
```

### Opción A — Probar con tus PDFs directamente (sin servidor)
```bash
# Crear carpeta pdfs/ y copiar tus REQs
mkdir pdfs
cp /ruta/de/tu/REQ_11031483.pdf pdfs/

# Ejecutar prueba — muestra todos los campos extraídos y guarda JSON
python test_local.py
```

### Opción B — Probar un PDF específico
```bash
python test_local.py REQ_11031483.pdf
```

### Opción C — Levantar el servidor local
```bash
python test_local.py --server
# Servidor en http://localhost:5000
```

### Probar con curl (cuando el servidor está corriendo)
```bash
# Health check
curl http://localhost:5000/health

# Extraer datos de un PDF
PDF_B64=$(base64 -w 0 REQ_11031483.pdf)
curl -X POST http://localhost:5000/extract \
  -H "Content-Type: application/json" \
  -d "{\"filename\": \"REQ_11031483.pdf\", \"content\": \"$PDF_B64\"}" \
  | python -m json.tool
```

---

## PASO 2 — SUBIR A HEROKU

### Prerequisitos
- Tener instalado [Heroku CLI](https://devcenter.heroku.com/articles/heroku-cli)
- Tener cuenta en [heroku.com](https://heroku.com) (gratis)

### Comandos (copiar y pegar en orden)
```bash
# 1. Inicializar git en el proyecto
cd req_api
git init
git add .
git commit -m "REQ Extractor API v1.0"

# 2. Crear app en Heroku
heroku login
heroku create req-extractor-planinternacional

# 3. Subir
git push heroku main

# 4. Verificar que está corriendo
heroku open /health
```

### Tu URL quedará así:
```
https://req-extractor-planinternacional.herokuapp.com/extract
```

---

## ENDPOINT DE LA API

### Request
```
POST /extract
Content-Type: application/json

{
  "filename": "REQ_11031483.pdf",   <- opcional
  "content":  "<base64 del PDF>"    <- requerido
}
```

### Respuesta exitosa (HTTP 200)
```json
{
  "metadata": {
    "extractedAt": "2026-02-19T10:30:00Z",
    "filename": "REQ_11031483.pdf",
    "pagesCount": 1
  },
  "header": {
    "PurchaseOrganisation":    "PRY1 Paraguay",
    "PurchaseGroup":           "542 PRY- CAAGUAZU",
    "RequisitionNumber":       "11031483",
    "PreparedBy":              "JUAN ANGEL ECHEVERRIA",
    "ApprovedBy":              "LAURA AMARILLA",
    "RequisitionCreationDate": "23.01.2026",
    "RequisitionApprovalDate": "27.01.2026",
    "RunDate":                 "27.01.2026",
    "PrintedBy":               "JECHEVERR",
    "REQDescription":          "Proyecto 2 Resultado 1.3 Talleres de capacitación..."
  },
  "items": [
    {
      "SN":                        "00010",
      "AccountAssignmentCategory": "P",
      "MaterialGroup":             "1038",
      "Description":               "Jugo en botella de 250 ml Resultado 1.3",
      "Unit":                      "C/U",
      "Quantity":                  "450.000",
      "Currency":                  "PYG",
      "Valuation":                 "1,012,500",
      "DeliveryDate":              "06.02.2026",
      "GLAccount":                 "666070",
      "CostCenter":                "PRJPY4047",
      "WBSElement":                "PY02160-4047-038-2711-01"
    }
  ],
  "summary": {
    "TotalValue": "4,837,500",
    "TotalItems": 3
  }
}
```

### Errores posibles
| HTTP | Causa |
|------|-------|
| 400  | Falta el campo `content`, o JSON mal formado |
| 422  | PDF escaneado (sin texto) o no es un REQ de Plan International |
| 500  | Error interno del servidor |

---

## CONFIGURACIÓN EN POWER AUTOMATE

Una vez que el API esté en Heroku, configura el Flow así:

**Acción: HTTP**
| Campo | Valor |
|-------|-------|
| Método | POST |
| URI | `https://req-extractor-planinternacional.herokuapp.com/extract` |
| Headers | `Content-Type: application/json` |
| Body | `{"filename": "@{triggerBody()?['file']?['name']}", "content": "@{triggerBody()?['file']?['contentBytes']}"}` |
