"""One parsing boundary for XML documents users supply (BPMN, SVG).

Ported from KEEN's ``app/security/xml.py``; keep the two aligned.

A document type declaration's internal subset can declare entities and default
attribute values, which multiply a document's size while it is parsed: a
diagram within the request limit could otherwise occupy gigabytes once its
tree is built. Expat's own amplification limit covers entities only, and lets
each entity grow up to a hundredfold. Diagrams have no use for an internal
subset, so such documents are refused before a tree is built. A declaration
that names only an external DTD is accepted by this parser (that DTD is never
fetched); MIDENA's callers refuse any declaration at all.

A namespace name multiplies too: the tree holds every distinct qualified name
as text that begins with its namespace name, so a document that declares one
long name and uses it on many short element or attribute names costs the
product of the two. BPMN and SVG namespaces are short, so a document
declaring a longer name is refused as well. Within those rules a tree still
costs many times its text, so documents are also bounded in size before
parsing.
"""

from xml.etree import ElementTree as ET
from xml.parsers import expat

# A tree costs many times the text it holds: each element is a Python object,
# each attribute a dictionary entry with two strings, and each distinct
# qualified name a string holding its namespace name. Whatever a document's
# shape, its tree needs at most several dozen times its size, so bounding the
# document bounds the tree. Diagrams run to hundreds of kilobytes; a document
# over this size is refused before any parsing, and the largest tree an
# accepted document builds stays within the API process's memory.
# tests/test_diagram_xml.py measures the costliest shapes.
MAX_DOCUMENT_BYTES = 3 * 1024 * 1024
# The namespace names diagrams declare run to about 60 characters. The bound is
# in bytes: the larger of the size a name is stored at and its UTF-8 length.
# A tree costs its number of distinct qualified names times what each is held
# in, and any element can declare another namespace, so this bound and the
# document bound together are what keep that product within the budget.
MAX_NAMESPACE_NAME = 96


def _refuse_internal_subset(
    name: str, system_id: str | None, public_id: str | None, has_internal_subset: bool
) -> None:
    if has_internal_subset:
        raise ET.ParseError("XML documents with an internal DTD subset are refused")


def _refuse_long_namespace_names(name: str, attributes: dict[str, str]) -> None:
    # Any element can declare a namespace, so every start tag is read.
    for attribute, value in attributes.items():
        if attribute == "xmlns" or attribute.startswith("xmlns:"):
            # Python stores every character of a string at the width of its
            # widest one: four bytes beyond the Basic Multilingual Plane, two
            # beyond U+00FF. One wide character in an otherwise ASCII name
            # widens all of it, which its UTF-8 length does not show, so both
            # sizes are bounded. Expat hands over decoded text, so a lone
            # surrogate cannot arrive; "surrogatepass" keeps the measure total.
            widest = max(value, default="")
            width = 4 if widest > "\uffff" else 2 if widest > "\xff" else 1
            encoded = len(value.encode("utf-8", "surrogatepass"))
            if max(len(value) * width, encoded) > MAX_NAMESPACE_NAME:
                raise ET.ParseError(
                    f"XML namespace names over {MAX_NAMESPACE_NAME} bytes are refused"
                )


def _refuse_any_doctype(
    name: str, system_id: str | None, public_id: str | None, has_internal_subset: bool
) -> None:
    raise ET.ParseError("XML documents with a document type declaration are refused")


def _refuse_processing_instruction(target: str, data: str) -> None:
    raise ET.ParseError("XML processing instructions are refused")


def parse_untrusted_xml(data: str | bytes, *, strict: bool = False) -> ET.Element:
    """Parse a document within the bounds above.

    ``strict`` (a MIDENA addition) also refuses any document type declaration
    and any processing instruction, such as ``<?xml-stylesheet?>``, for
    documents that are stored and served as written. The XML declaration is
    not a processing instruction and stays accepted.
    """
    # The bound is on bytes. Text is measured as the UTF-8 the parser reads:
    # one character of text can be a whole element name, so a count of
    # characters admits more distinct names than the same count of bytes.
    if len(data) > MAX_DOCUMENT_BYTES or (
        isinstance(data, str)
        and len(data.encode("utf-8", "surrogatepass")) > MAX_DOCUMENT_BYTES
    ):
        raise ET.ParseError(
            f"XML documents over {MAX_DOCUMENT_BYTES // (1024 * 1024)} MiB are refused"
        )
    # One pass that builds no tree and resolves no namespaces, so it holds no
    # qualified names; names are not kept between elements either.
    screen = expat.ParserCreate(intern=None)
    screen.StartDoctypeDeclHandler = (
        _refuse_any_doctype if strict else _refuse_internal_subset
    )
    if strict:
        screen.ProcessingInstructionHandler = _refuse_processing_instruction
    screen.StartElementHandler = _refuse_long_namespace_names
    try:
        screen.Parse(data, True)
    except expat.ExpatError as exc:
        error = ET.ParseError(str(exc))
        error.code, error.position = exc.code, (exc.lineno, exc.offset)
        raise error from None
    return ET.fromstring(data)
