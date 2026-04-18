"""Tests for language_java.JavaAnalyzer."""

from __future__ import annotations

from pathlib import Path

from contracts.interfaces import DependencyEdge, LanguageAnalyzer, Symbol
from language_java import JavaAnalyzer

SAMPLE_JAVA = """\
package com.example;

import java.util.List;
import java.util.Map;

public class UserService {
    private String name;

    public String getName() {
        return this.name;
    }

    public void setName(String name) {
        this.name = name;
    }
}
"""


def test_import():
    import language_java  # noqa: F401


def test_implements_protocol():
    assert isinstance(JavaAnalyzer(), LanguageAnalyzer)


SAMPLE_CTOR_AND_ANNOTATIONS = """\
package com.example;

@RestController
@RequestMapping("/users")
public class UserController {

    private final UserService userService;

    @Autowired
    public UserController(UserService userService) {
        this.userService = userService;
    }

    @GetMapping("/{id}")
    @Transactional
    public String findOne(long id) {
        return userService.find(id);
    }
}
"""


def test_extracts_constructor_declaration(tmp_path: Path):
    f = tmp_path / "UserController.java"
    f.write_text(SAMPLE_CTOR_AND_ANNOTATIONS)
    results = JavaAnalyzer().analyze(f)
    ctors = [s for s in results if isinstance(s, Symbol) and s.kind == "constructor"]
    assert any(s.name == "UserController" for s in ctors)


def test_extracts_all_annotations_in_signature(tmp_path: Path):
    f = tmp_path / "UserController.java"
    f.write_text(SAMPLE_CTOR_AND_ANNOTATIONS)
    results = JavaAnalyzer().analyze(f)
    classes = [s for s in results if isinstance(s, Symbol) and s.kind == "class"]
    controller = next((s for s in classes if s.name == "UserController"), None)
    assert controller is not None
    assert "@RestController" in controller.signature
    assert "@RequestMapping" in controller.signature

    methods = [s for s in results if isinstance(s, Symbol) and s.kind == "method"]
    find_one = next((s for s in methods if s.name == "findOne"), None)
    assert find_one is not None
    assert "@GetMapping" in find_one.signature
    assert "@Transactional" in find_one.signature


def test_returns_list(tmp_path: Path):
    result = JavaAnalyzer().analyze(tmp_path / "nonexistent.java")
    assert isinstance(result, list)


def test_extracts_class(tmp_path: Path):
    f = tmp_path / "UserService.java"
    f.write_text(SAMPLE_JAVA)
    results = JavaAnalyzer().analyze(f)

    classes = [s for s in results if isinstance(s, Symbol) and s.kind == "class"]
    names = {s.name for s in classes}
    assert "UserService" in names


def test_extracts_methods(tmp_path: Path):
    f = tmp_path / "UserService.java"
    f.write_text(SAMPLE_JAVA)
    results = JavaAnalyzer().analyze(f)

    methods = [s for s in results if isinstance(s, Symbol) and s.kind == "method"]
    names = {s.name for s in methods}
    assert "getName" in names
    assert "setName" in names


def test_extracts_imports_as_edges(tmp_path: Path):
    f = tmp_path / "UserService.java"
    f.write_text(SAMPLE_JAVA)
    results = JavaAnalyzer().analyze(f)

    import_edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "imports"]
    assert len(import_edges) >= 1
    to_symbols = {e.to_symbol for e in import_edges}
    # java.util.List → leaf "List"
    assert "List" in to_symbols


def test_line_numbers_set(tmp_path: Path):
    f = tmp_path / "UserService.java"
    f.write_text(SAMPLE_JAVA)
    results = JavaAnalyzer().analyze(f)

    for s in results:
        if isinstance(s, Symbol) and s.kind in ("class", "method"):
            assert s.line_start > 0, f"{s.name} has no line_start"


def test_empty_file(tmp_path: Path):
    f = tmp_path / "Empty.java"
    f.write_text("")
    results = JavaAnalyzer().analyze(f)
    assert results == []


def test_invalid_path_returns_empty():
    results = JavaAnalyzer().analyze(Path("/nonexistent/File.java"))
    assert results == []


SAMPLE_JAVA_WITH_CALLS = """\
package com.example;

public class OrderService {
    private UserService userService;

    public void processOrder(String userId) {
        validateUser(userId);
        buildOrder(userId);
    }

    private void validateUser(String id) {
        userService.checkPermissions(id);
    }

    private void buildOrder(String id) {
    }
}
"""


def test_call_edges(tmp_path: Path):
    f = tmp_path / "OrderService.java"
    f.write_text(SAMPLE_JAVA_WITH_CALLS)
    results = JavaAnalyzer().analyze(f)

    call_edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "calls"]
    callee_names = {e.to_symbol for e in call_edges}
    assert "validateUser" in callee_names
    assert "buildOrder" in callee_names


def test_call_edges_have_method_as_source(tmp_path: Path):
    f = tmp_path / "OrderService.java"
    f.write_text(SAMPLE_JAVA_WITH_CALLS)
    results = JavaAnalyzer().analyze(f)

    call_edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "calls"]
    sources = {e.from_symbol for e in call_edges}
    # Call edges originate from method names, not file paths
    assert "processOrder" in sources


# ---------------------------------------------------------------------------
# v3 phase1/interface-kind-label: kind correctness across type declarations.
# ---------------------------------------------------------------------------

SAMPLE_JAVA_ALL_KINDS = """\
package com.example;

public class Person {
    private String name;
}

interface Greeter {
    String greet();
}

enum Status {
    ACTIVE,
    INACTIVE
}
"""


def test_kind_labels_class_interface_enum(tmp_path: Path):
    """Each Java type-declaration node-type must map to its matching kind."""
    f = tmp_path / "AllKinds.java"
    f.write_text(SAMPLE_JAVA_ALL_KINDS)
    results = JavaAnalyzer().analyze(f)

    by_name = {
        s.name: s.kind
        for s in results
        if isinstance(s, Symbol) and s.kind in {"class", "interface", "enum"}
    }
    assert by_name.get("Person") == "class"
    assert by_name.get("Greeter") == "interface"
    assert by_name.get("Status") == "enum"


def test_plain_class_regression_still_kind_class(tmp_path: Path):
    """Regression: a plain class in isolation stays kind='class' (unchanged)."""
    f = tmp_path / "UserService.java"
    f.write_text(SAMPLE_JAVA)  # Only contains a plain class.
    results = JavaAnalyzer().analyze(f)

    classes = [s for s in results if isinstance(s, Symbol) and s.kind == "class"]
    assert "UserService" in {s.name for s in classes}


# ---------------------------------------------------------------------------
# v3 phase3/enum-symbols-extracted: Java enums must emit kind='enum'.
# ---------------------------------------------------------------------------

def test_extracts_enum_declaration_single_file(tmp_path: Path):
    """A standalone Java enum produces exactly one kind='enum' symbol."""
    f = tmp_path / "Color.java"
    f.write_text("public enum Color { RED, GREEN, BLUE }\n")
    results = JavaAnalyzer().analyze(f)

    enum_symbols = [
        s for s in results
        if isinstance(s, Symbol) and s.name == "Color"
    ]
    kinds = [s.kind for s in enum_symbols]
    assert kinds == ["enum"], f"expected ['enum'], got {kinds}"
    # Negative: the enum must not also leak out as kind='class'.
    classes = [s for s in results if isinstance(s, Symbol) and s.kind == "class"]
    assert "Color" not in {s.name for s in classes}
    # Exactly one enum symbol emitted for this file.
    all_enums = [s for s in results if isinstance(s, Symbol) and s.kind == "enum"]
    assert len(all_enums) == 1


# ---------------------------------------------------------------------------
# v3 phase3/edge-kinds-extended: extends / implements / tested_by edges.
# ---------------------------------------------------------------------------

SAMPLE_JAVA_INHERITANCE = """\
package com.example;

public class Dog extends Animal implements Trainable, Feedable {
    public void bark() {}
}

public interface Repo extends JpaRepository<Owner, Integer>, QueryBuilder {
    void save();
}
"""


def test_extends_edge_from_class(tmp_path: Path):
    f = tmp_path / "Dog.java"
    f.write_text(SAMPLE_JAVA_INHERITANCE)
    results = JavaAnalyzer().analyze(f)
    edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "extends"]
    pairs = {(e.from_symbol, e.to_symbol) for e in edges}
    assert ("Dog", "Animal") in pairs, f"expected Dog->Animal extends, got {pairs}"


def test_implements_edges_from_class(tmp_path: Path):
    f = tmp_path / "Dog.java"
    f.write_text(SAMPLE_JAVA_INHERITANCE)
    results = JavaAnalyzer().analyze(f)
    edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "implements"]
    pairs = {(e.from_symbol, e.to_symbol) for e in edges}
    # Exactly two implements: Trainable, Feedable.
    assert ("Dog", "Trainable") in pairs
    assert ("Dog", "Feedable") in pairs


def test_interface_extends_yields_extends_edges(tmp_path: Path):
    """interface Repo extends JpaRepository<...> → extends edge (generic stripped)."""
    f = tmp_path / "Repo.java"
    f.write_text(SAMPLE_JAVA_INHERITANCE)
    results = JavaAnalyzer().analyze(f)
    edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "extends"]
    pairs = {(e.from_symbol, e.to_symbol) for e in edges}
    assert ("Repo", "JpaRepository") in pairs, (
        f"expected generic-stripped Repo->JpaRepository, got {pairs}"
    )
    assert ("Repo", "QueryBuilder") in pairs


SAMPLE_JAVA_TEST = """\
package com.example;

public class PetControllerTests {

    @Test
    void initCreationForm() throws Exception {}

    @Test
    void processUpdateFormSuccess() throws Exception {}

    @BeforeEach
    void setUp() {}
}
"""


def test_tested_by_edges_in_test_file(tmp_path: Path):
    """A Java test file ``FooTests.java`` emits tested_by edges from ``Foo``
    (the inferred SUT) to each ``@Test``-annotated method."""
    f = tmp_path / "PetControllerTests.java"
    f.write_text(SAMPLE_JAVA_TEST)
    results = JavaAnalyzer().analyze(f)
    edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "tested_by"]
    pairs = {(e.from_symbol, e.to_symbol) for e in edges}
    assert ("PetController", "initCreationForm") in pairs
    assert ("PetController", "processUpdateFormSuccess") in pairs
    # ``@BeforeEach`` is not a test method — no tested_by for ``setUp``.
    assert ("PetController", "setUp") not in pairs


def test_no_inheritance_or_tested_by_in_plain_class(tmp_path: Path):
    """Negative: a plain class file yields zero extends/implements/tested_by."""
    f = tmp_path / "UserService.java"
    f.write_text(SAMPLE_JAVA)
    results = JavaAnalyzer().analyze(f)
    spec_edges = [
        r for r in results
        if isinstance(r, DependencyEdge)
        and r.edge_type in {"extends", "implements", "tested_by"}
    ]
    assert spec_edges == []


def test_calls_and_imports_unchanged_after_v3(tmp_path: Path):
    """Regression: adding extends/implements/tested_by did not change ``calls``
    / ``imports`` emission counts on the existing call-chain fixture."""
    f = tmp_path / "OrderService.java"
    f.write_text(SAMPLE_JAVA_WITH_CALLS)
    results = JavaAnalyzer().analyze(f)
    calls = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "calls"]
    imports = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "imports"]
    # calls: validateUser + buildOrder + checkPermissions = 3 calls.
    assert len(calls) >= 3
    # no imports in this fixture
    assert imports == []
