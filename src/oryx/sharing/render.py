"""Create an in-memory local rendition of approved prose and its source timestamp."""
from io import BytesIO
import re
from xml.sax.saxutils import escape
import zipfile

MIME = {"md":"text/markdown; charset=utf-8","pdf":"application/pdf",
        "docx":"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


def office(fmt, lines):
    prefix = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    ns = "http://schemas.openxmlformats.org/"
    rel = ns + "officeDocument/2006/relationships/"
    pkgrel = ns + "package/2006/relationships"
    content = ns + "package/2006/content-types"
    def relationships(items):
        return '<Relationships xmlns="' + pkgrel + '">' + ''.join(f'<Relationship Id="{a}" Type="{rel}{b}" Target="{c}"/>' for a,b,c in items) + '</Relationships>'
    if fmt=="docx":
        main="word/document.xml"
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
        body=''.join('<w:p><w:r><w:t xml:space="preserve">'+escape(line)+'</w:t></w:r></w:p>' for line in lines)
        parts={main:'<w:document xmlns:w="'+ns+'wordprocessingml/2006/main"><w:body>'+body+'</w:body></w:document>'}
    else:
        main="xl/workbook.xml"
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
        sheet=ns+"spreadsheetml/2006/main"
        if any(len(line)>32767 for line in lines):
            raise ValueError("A paragraph exceeds the XLSX cell limit; select another format")
        rows=''.join(f'<row r="{i}"><c r="A{i}" t="inlineStr"><is><t xml:space="preserve">{escape(line)}</t></is></c></row>' for i,line in enumerate(lines,1))
        parts={main:'<workbook xmlns="'+sheet+'" xmlns:r="'+rel[:-1]+'"><sheets><sheet name="Document" sheetId="1" r:id="r1"/></sheets></workbook>',
               "xl/_rels/workbook.xml.rels":relationships([("r1","worksheet","worksheets/sheet1.xml")]),
               "xl/worksheets/sheet1.xml":'<worksheet xmlns="'+sheet+'"><sheetData>'+rows+'</sheetData></worksheet>'}
    declarations=f'<Override PartName="/{main}" ContentType="{mime}"/>'
    if fmt=="xlsx":
        declarations+='<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    parts["_rels/.rels"]=relationships([("r1","officeDocument",main)])
    parts["[Content_Types].xml"]='<Types xmlns="'+content+'"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'+declarations+'</Types>'
    out=BytesIO()
    with zipfile.ZipFile(out,"w") as archive:
        for name, data in sorted(parts.items()):
            entry=zipfile.ZipInfo(name,(1980,1,1,0,0,0))
            archive.writestr(entry,(prefix+data).encode(),compress_type=zipfile.ZIP_DEFLATED)
    return out.getvalue()


def rendition(fmt, text, stamp):
    if fmt not in MIME or not isinstance(text,str) or not isinstance(stamp,str):
        raise ValueError("Choose md, docx, xlsx or pdf with a source timestamp")
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]",text):
        raise ValueError("The source contains unrenderable control characters")
    final=text+"\n\nSource last updated: "+stamp+"\n"
    if fmt=="md":
        return final.encode()
    if fmt in {"docx","xlsx"}:
        return office(fmt,final.splitlines())
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.utils import simpleSplit
    except ImportError as exc:
        raise ValueError("PDF export needs the optional ReportLab renderer") from exc
    try:
        final.encode("cp1252")
    except UnicodeEncodeError as exc:
        raise ValueError("PDF font cannot represent this document; use a lossless offered format") from exc
    out=BytesIO()
    pdf=canvas.Canvas(out,pagesize=(612,792),invariant=1)
    y=740
    for line in final.splitlines():
        for part in simpleSplit(line,"Helvetica",10,510) or [""]:
            if pdf.stringWidth(part,"Helvetica",10)>510:
                raise ValueError("A source token exceeds the PDF page width; use a lossless offered format")
            if y<55:
                pdf.showPage();y=740
            pdf.setFont("Helvetica",10)
            pdf.drawString(50,y,part)
            y-=14
    pdf.save()
    return out.getvalue()
