
from pathlib import Path
import zipfile, os, re, shutil, tempfile, argparse
import xml.etree.ElementTree as ET

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"
ET.register_namespace("", OPF_NS)
ET.register_namespace("dc", DC_NS)

def chapter_title(path: Path) -> str:
    s = path.read_text(encoding="utf-8", errors="ignore")
    if BeautifulSoup is not None:
        soup = BeautifulSoup(s, "html.parser")
        h = soup.find(["h1", "h2", "title"])
        txt = h.get_text(" ", strip=True) if h else path.stem
    else:
        m = re.search(r"<h[12][^>]*>(.*?)</h[12]>", s, flags=re.I | re.S)
        txt = re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else path.stem
    return txt.strip() or path.stem

def merge_epubs(part1: Path, part2: Path, out: Path):
    tmp = Path(tempfile.mkdtemp(prefix="merge_epubs_"))
    d1 = tmp / "p1"
    d2 = tmp / "p2"
    d1.mkdir()
    d2.mkdir()

    with zipfile.ZipFile(part1) as z:
        z.extractall(d1)
    with zipfile.ZipFile(part2) as z:
        z.extractall(d2)

    ep1 = d1 / "EPUB"
    ep2 = d2 / "EPUB"
    if not ep1.exists() or not ep2.exists():
        raise RuntimeError("No se encontró la carpeta EPUB dentro de uno de los archivos.")

    chap1 = sorted(ep1.glob("chap_*.xhtml"))
    chap2 = sorted(ep2.glob("chap_*.xhtml"))
    if not chap1 or not chap2:
        raise RuntimeError("No se encontraron capítulos chap_*.xhtml en uno de los EPUB.")

    titles1 = [chapter_title(p) for p in chap1]
    titles2 = [chapter_title(p) for p in chap2]

    # Copiar capítulos de la parte 2 continuando la numeración
    for idx, src in enumerate(chap2, start=len(chap1) + 1):
        shutil.copy2(src, ep1 / f"chap_{idx:04d}.xhtml")

    all_chaps = sorted(ep1.glob("chap_*.xhtml"))
    titles = titles1 + titles2

    # Actualizar content.opf
    tree = ET.parse(ep1 / "content.opf")
    root = tree.getroot()
    ns = {"opf": OPF_NS, "dc": DC_NS}
    manifest = root.find("opf:manifest", ns)
    spine = root.find("opf:spine", ns)
    metadata = root.find("opf:metadata", ns)

    if manifest is None or spine is None or metadata is None:
        raise RuntimeError("content.opf no tiene la estructura esperada.")

    old_manifest = list(manifest)
    for item in list(manifest):
        manifest.remove(item)
    pre, post = [], []
    for item in old_manifest:
        href = item.get("href", "")
        if re.match(r"chap_\d+\.xhtml$", href):
            continue
        if item.get("id") in ("ncx", "nav"):
            post.append(item)
        else:
            pre.append(item)

    for item in pre:
        manifest.append(item)
    for i, chap in enumerate(all_chaps):
        manifest.append(
            ET.Element(
                f"{{{OPF_NS}}}item",
                {
                    "href": chap.name,
                    "id": f"chapter_{i}",
                    "media-type": "application/xhtml+xml",
                },
            )
        )
    for item in post:
        manifest.append(item)

    for itemref in list(spine):
        spine.remove(itemref)
    for i in range(len(all_chaps)):
        spine.append(ET.Element(f"{{{OPF_NS}}}itemref", {"idref": f"chapter_{i}"}))

    tree.write(ep1 / "content.opf", encoding="utf-8", xml_declaration=True)

    # Rehacer nav.xhtml
    nav_title = "EPUB"
    t_el = metadata.find("dc:title", ns)
    if t_el is not None and t_el.text:
        nav_title = t_el.text

    nav_lines = [
        "<?xml version='1.0' encoding='utf-8'?>",
        "<!DOCTYPE html>",
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="es" xml:lang="es">',
        "  <head>",
        f"    <title>{nav_title}</title>",
        "  </head>",
        "  <body>",
        '    <nav epub:type="toc" id="id" role="doc-toc">',
        f"      <h2>{nav_title}</h2>",
        "      <ol>",
    ]
    for i, title in enumerate(titles, start=1):
        safe_title = (
            title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        nav_lines += [
            "        <li>",
            f'          <a href="chap_{i:04d}.xhtml">{safe_title}</a>',
            "        </li>",
        ]
    nav_lines += ["      </ol>", "    </nav>", "  </body>", "</html>"]
    (ep1 / "nav.xhtml").write_text("\n".join(nav_lines), encoding="utf-8")

    # Rehacer toc.ncx si existe
    ncx = ep1 / "toc.ncx"
    if ncx.exists():
        uid = "merged-epub"
        id_el = metadata.find("dc:identifier", ns)
        if id_el is not None and id_el.text:
            uid = id_el.text

        ncx_lines = [
            "<?xml version='1.0' encoding='utf-8'?>",
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">',
            "  <head>",
            f'    <meta content="{uid}" name="dtb:uid"/>',
            '    <meta content="1" name="dtb:depth"/>',
            '    <meta content="0" name="dtb:totalPageCount"/>',
            '    <meta content="0" name="dtb:maxPageNumber"/>',
            "  </head>",
            "  <docTitle>",
            f"    <text>{nav_title}</text>",
            "  </docTitle>",
            "  <navMap>",
        ]
        for i, title in enumerate(titles, start=1):
            safe_title = (
                title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            )
            ncx_lines += [
                f'    <navPoint id="chapter_{i-1}" playOrder="{i}">',
                "      <navLabel>",
                f"        <text>{safe_title}</text>",
                "      </navLabel>",
                f'      <content src="chap_{i:04d}.xhtml"/>',
                "    </navPoint>",
            ]
        ncx_lines += ["  </navMap>", "</ncx>"]
        ncx.write_text("\n".join(ncx_lines), encoding="utf-8")

    # Empaquetar EPUB
    if out.exists():
        out.unlink()

    with zipfile.ZipFile(out, "w") as z:
        z.write(d1 / "mimetype", "mimetype", compress_type=zipfile.ZIP_STORED)
        for rootdir, dirs, files in os.walk(d1):
            for f in files:
                p = Path(rootdir) / f
                rel = p.relative_to(d1).as_posix()
                if rel == "mimetype":
                    continue
                z.write(p, rel, compress_type=zipfile.ZIP_DEFLATED)

    print(f"Creado: {out}")
    print(f"Capítulos totales: {len(all_chaps)}")
    print(f"Primer capítulo: {all_chaps[0].name}")
    print(f"Último capítulo: {all_chaps[-1].name}")

def main():
    ap = argparse.ArgumentParser(description="Une dos EPUB partidos en uno solo.")
    ap.add_argument("part1", type=Path, help="EPUB parte 1")
    ap.add_argument("part2", type=Path, help="EPUB parte 2")
    ap.add_argument("-o", "--output", type=Path, required=True, help="EPUB de salida")
    args = ap.parse_args()
    merge_epubs(args.part1, args.part2, args.output)

if __name__ == "__main__":
    main()
