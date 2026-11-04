from local_ai_hub.rag import _python_ast_chunks
from local_ai_hub.services import _rag_fragment_matches_source


def test_python_chunks_keep_module_level_assignments_and_statements():
    source = '"""module doc"""\nIMPORTANT_SETTING = "needle-setting"\n\ndef work():\n    return 1\n\nif __name__ == "__main__":\n    print("needle-entry")\n'
    chunks = _python_ast_chunks(source, size=90, overlap=10)
    assert any("needle-setting" in chunk for chunk in chunks)
    assert any("needle-entry" in chunk for chunk in chunks)
    assert all(len(chunk) <= 90 for chunk in chunks)


def test_python_chunks_are_verifiable_contiguous_source_fragments():
    source = '"""module doc"""\nSETTING = "value"\n\ndef work():\n    return 1\n\nif __name__ == "__main__":\n    print("entry")\n'
    chunks = _python_ast_chunks(source, size=90, overlap=10)

    assert chunks
    assert all(_rag_fragment_matches_source(chunk, source) for chunk in chunks)


def test_python_chunks_keep_large_class_attributes_and_nested_classes():
    source = "class Example:\n    IMPORTANT = 'needle-class'\n    class Nested:\n        value = 'needle-nested'\n    def method(self):\n        return '" + "x" * 160 + "'\n"
    chunks = _python_ast_chunks(source, size=110, overlap=10)
    assert any("needle-class" in chunk for chunk in chunks)
    assert any("needle-nested" in chunk for chunk in chunks)
    assert all(len(chunk) <= 110 for chunk in chunks)
