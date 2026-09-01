from pathlib import Path

from run_local_kb_online import (
    DEFAULT_COMPLEX_QUERY_DATASET,
    DEFAULT_DATASET,
    DEFAULT_SIMPLE_DATASET,
    load_complex_cases,
    load_simple_cases,
    select_cases,
)


def test_online_case_sets_are_separated_by_complexity() -> None:
    simple = load_simple_cases(DEFAULT_SIMPLE_DATASET)
    complex_cases = load_complex_cases(DEFAULT_DATASET)

    assert len(simple) == 8
    assert len(complex_cases) == 13
    assert {case["test_complexity"] for case in simple} == {"simple"}
    assert {case["test_complexity"] for case in complex_cases} == {"complex"}
    assert not ({case["id"] for case in simple} & {case["id"] for case in complex_cases})
    assert all(case["query"].isascii() for case in simple)
    assert all(case["query"].isascii() for case in complex_cases)


def test_case_selection_supports_ids_and_limit() -> None:
    cases = load_simple_cases(DEFAULT_SIMPLE_DATASET)
    selected = select_cases(cases, [cases[2]["id"], cases[5]["id"]], 1)

    assert [case["id"] for case in selected] == [cases[2]["id"]]


def test_default_dataset_paths_exist() -> None:
    assert Path(DEFAULT_DATASET).is_file()
    assert Path(DEFAULT_SIMPLE_DATASET).is_file()
    assert Path(DEFAULT_COMPLEX_QUERY_DATASET).is_file()


def test_simple_corrective_retrieval_accepts_common_english_wording() -> None:
    cases = load_simple_cases(DEFAULT_SIMPLE_DATASET)
    case = next(
        item for item in cases
        if item["id"] == "local_simple_corrective_retrieval_limit"
    )

    assert "only one" in case["required_facts"][0]
