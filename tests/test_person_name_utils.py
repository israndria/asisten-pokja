from person_name_utils import clean_person_name, format_equipment_entry


def test_clean_person_name_removes_job_title_and_academic_titles():
    assert clean_person_name("Ir. Muhammad Iqbal (Pelaksana Lapangan), S.T.") == "Muhammad Iqbal"


def test_equipment_entry_has_unit():
    assert format_equipment_entry("Dump Truck", "1") == "Dump Truck (1 Unit)"
