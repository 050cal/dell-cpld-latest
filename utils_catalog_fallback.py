import io, gzip, requests, xml.etree.ElementTree as ET

CATALOG_URL = "https://downloads.dell.com/catalog/Catalog.xml.gz"

def load_catalog_xml():
    r = requests.get(CATALOG_URL, timeout=60)
    r.raise_for_status()
    with gzip.GzipFile(fileobj=io.BytesIO(r.content)) as gz:
        xml_bytes = gz.read()
    return ET.fromstring(xml_bytes)

def best_cpld_for_model_from_catalog(root: ET.Element, model_hint: str):
    """
    Simple heuristic:
    - Look for SoftwareComponent where Name or Category contains 'CPLD'.
    - Check if SupportedSystems includes the model hint (e.g., 'PowerEdge R750').
    - Return newest by ReleaseDate string (Dell uses ISO-like format here).
    """
    model_hint_l = model_hint.replace("-", " ").lower()
    candidates = []
    for comp in root.findall(".//SoftwareComponent"):
        cat = (comp.findtext("Category") or "").lower()
        name = (comp.findtext("Name") or "").lower()
        if "cpld" not in name and "cpld" not in cat:
            continue
        systems = " ".join([m.text or "" for m in comp.findall(".//SupportedSystems/Brand/Model")]).lower()
        if model_hint_l not in systems:
            continue
        ver = comp.findtext("Version")
        dte = comp.findtext("ReleaseDate") or ""
        url = comp.findtext("Path")
        candidates.append((dte, {
            "name": comp.findtext("Name"),
            "version": ver,
            "release_date": dte,
            "download_url": url,
            "category": comp.findtext("Category"),
            "driver_id": comp.findtext("DellVer")  # often blank; retained for schema consistency
        }))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0], reverse=True)
    return candidates[0][1]
