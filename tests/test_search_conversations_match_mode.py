from lib.memory_db import MemoryDB


def test_all_terms_mode_filters_single_term_noise(tmp_path):
    db = MemoryDB(str(tmp_path / "memory.db"))
    try:
        relevant_id = db.log_conversation(
            "Deploy the app with Coolify",
            "The persistent mounts still need configuration.",
            session_id="relevant",
        )
        noisy_id = db.log_conversation(
            "Cheese ingredient amounts",
            "Nothing about application deployment.",
            session_id="noise",
        )

        broad_results = db.search_conversations(
            "coolify mounts",
            limit=10,
        )
        all_terms_results = db.search_conversations(
            "coolify mounts",
            limit=10,
            match_mode="all_terms",
        )
    finally:
        db.close()

    assert {row["id"] for row in broad_results} == {relevant_id, noisy_id}
    assert [row["id"] for row in all_terms_results] == [relevant_id]


def test_exact_phrase_still_wins_in_all_terms_mode(tmp_path):
    db = MemoryDB(str(tmp_path / "memory.db"))
    try:
        exact_id = db.log_conversation(
            "I need help with coolify mounts",
            "We should inspect the existing configuration.",
            session_id="exact",
        )
        db.log_conversation(
            "Coolify deployment",
            "Mounts are discussed separately.",
            session_id="all-terms-only",
        )

        results = db.search_conversations(
            "coolify mounts",
            limit=10,
            match_mode="all_terms",
        )
    finally:
        db.close()

    assert [row["id"] for row in results] == [exact_id]
