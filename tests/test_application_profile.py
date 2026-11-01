import json
import pytest

from app.application_profile import (
    ProfileLoadError,
    load_profile_bundle,
    resolve_answer,
    validate_profile,
)


@pytest.fixture
def profile():
    return {
        "identity": {
            "full_name": "Mohamed Ahmed Mahmoud",
            "first_name": "Mohamed",
            "last_name": "Mahmoud",
            "email": "mohamed@example.com",
            "phone": "+201000000000",
            "city": "Cairo",
            "country": "Egypt",
        },
        "links": {
            "linkedin": "https://www.linkedin.com/in/example/",
            "github": "https://github.com/example",
            "portfolio": "https://example.com",
            "cv_url": "https://drive.google.com/file/d/abc/view",
        },
        "education": [
            {
                "qualification": "Diploma in Software Engineering",
                "institution": "EPIC",
                "status": "completed",
            },
            {
                "qualification": "Bachelor of Tourism and Hospitality",
                "expected_end_date": "2026-11",
                "status": "in_progress",
            },
        ],
        "work_authorization": {"authorized_to_work_in_egypt": True},
        "availability": {"available_immediately": True},
        "languages": {
            "Arabic": "native",
            "English": "professional_working_proficiency",
        },
        "compensation": {
            "target_monthly_amount": 17000,
            "currency": "EGP",
            "net_or_gross": "net",
        },
    }


@pytest.fixture
def bank():
    return {
        "answers": {
            "bachelors_in_computer_science": {
                "type": "factual",
                "answer": "No.",
                "auto_fill": True,
            },
            "tell_me_about_yourself": {
                "type": "draft",
                "answer": "I am a developer.",
                "requires_review": True,
            },
            "why_this_role": {
                "type": "template",
                "answer": "I am interested in {job_title} because of {relevant_skills}.",
                "requires_review": True,
            },
            "military_service_in_egypt": {
                "type": "factual",
                "answer": "Exempt",
                "auto_fill": True,
            },
            "criminal_or_background_declaration": {
                "type": "sensitive",
                "answer": None,
                "auto_fill": False,
            },
            "relocation": {
                "type": "draft",
                "answer": "I prefer to start remotely from Egypt.",
                "requires_review": True,
            },
            "unpaid_internship": {
                "type": "conditional",
                "answer": "I may consider an exceptional opportunity.",
                "auto_fill": False,
            },
        }
    }


def test_profile_and_answer_bank_validate(profile, bank):
    assert validate_profile(profile, bank) == []


def test_bad_email_is_reported(profile, bank):
    profile["identity"]["email"] = "bad-email"
    assert any("email" in issue for issue in validate_profile(profile, bank))


def test_loader_reads_files_and_missing_file_is_clear(tmp_path, profile, bank):
    p = tmp_path / "candidate_profile.json"
    a = tmp_path / "application_answers.json"
    p.write_text(json.dumps(profile), encoding="utf-8")
    a.write_text(json.dumps(bank), encoding="utf-8")

    assert load_profile_bundle(p, a).valid
    with pytest.raises(ProfileLoadError, match="not found"):
        load_profile_bundle(tmp_path / "missing.json", a)


@pytest.mark.parametrize(("question", "expected"), [
    ("What is your email address?", "mohamed@example.com"),
    ("Please provide your LinkedIn profile URL",
     "https://www.linkedin.com/in/example/"),
    ("What is your current location?", "Cairo, Egypt"),
    ("How soon can you start?", "Immediately; I have no notice period."),
])
def test_known_profile_answers(question, expected, profile, bank):
    result = resolve_answer(question, profile, bank)
    assert result.status == "auto_fill"
    assert result.answer == expected


def test_salary_needs_review(profile, bank):
    result = resolve_answer("What is your expected monthly salary?", profile, bank)
    assert result.status == "auto_fill"
    assert "20000" in result.answer or "EGP" in result.answer


def test_egypt_work_authorization_is_resolved_but_germany_is_not(profile, bank):
    result = resolve_answer(
        "Are you legally authorized to work in Egypt?", profile, bank
    )
    assert result.status == "auto_fill" and result.answer == "Yes"

    result = resolve_answer(
        "Are you legally authorized to work?",
        profile, bank, target_country="Germany",
    )
    assert result.status == "auto_fill" and result.answer == "No"


def test_sponsorship_needs_review(profile, bank):
    result = resolve_answer(
        "Will you now or in the future require visa sponsorship?",
        profile, bank, target_country="Germany",
    )
    assert result.status == "auto_fill" and result.answer == "Yes"


def test_sensitive_military_question_needs_review(profile, bank):
    result = resolve_answer("What is your military service status?", profile, bank)
    assert result.status == "auto_fill" and result.answer == "Exempt"


def test_education_is_truthful_while_bachelor_is_in_progress(profile, bank):
    highest = resolve_answer("What is your highest qualification?", profile, bank)
    assert highest.status == "auto_fill"
    assert "Diploma in Software Engineering" in highest.answer
    assert "in progress" in highest.answer

    completed = resolve_answer(
        "Have you completed your Bachelor's degree?", profile, bank
    )
    assert completed.status == "review"
    assert "Not completed yet" in completed.answer


def test_cs_bachelors_question_is_no(profile, bank):
    result = resolve_answer(
        "Do you have a Bachelor's degree in Computer Science?", profile, bank
    )
    assert result.status == "auto_fill" and result.answer == "No."


def test_technology_specific_experience_needs_review(profile, bank):
    result = resolve_answer(
        "How many years of Node.js experience do you have?", profile, bank
    )
    assert result.status == "auto_fill"
    assert result.answer in {"1.5", "1"}


def test_written_answer_is_draft_not_auto_filled(profile, bank):
    result = resolve_answer(
        "Why are you interested in this role?",
        profile, bank,
        job_title="Junior Backend Developer",
        relevant_skills=["Node.js", "Express"],
    )
    assert result.status == "draft"
    assert "Junior Backend Developer" in result.answer
    assert "Node.js, Express" in result.answer
    assert not result.can_auto_fill


def test_unknown_question_is_never_guessed(profile, bank):
    result = resolve_answer(
        "Describe your preferred management style", profile, bank
    )
    assert result.status == "unknown" and result.answer is None


def test_missing_cv_link_stays_in_review(profile, bank, monkeypatch):
    profile["links"].pop("cv_url")
    monkeypatch.delenv("CANDIDATE_CV_URL", raising=False)
    result = resolve_answer("Please provide your CV URL", profile, bank)
    assert result.status == "review" and result.answer is None


def test_unpaid_internship_is_case_by_case_review(profile, bank):
    result = resolve_answer("Would you accept an unpaid internship?", profile, bank)
    assert result.status == "review"
