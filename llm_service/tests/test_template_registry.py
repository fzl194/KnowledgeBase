import pytest

pytestmark = pytest.mark.asyncio


async def test_create_template(db):
    from llm_service.runtime.template_registry import TemplateRegistry

    reg = TemplateRegistry(db)
    tpl_id = await reg.create(
        template_key="summarize",
        template_version="v1",
        purpose="Summarize document",
        user_prompt_template="Summarize: {{content}}",
        expected_output_type="json_object",
    )
    assert tpl_id is not None

    cur = await db.execute("SELECT template_key, status FROM agent_llm_prompt_templates WHERE id = ?", (tpl_id,))
    row = await cur.fetchone()
    assert row["template_key"] == "summarize"
    assert row["status"] == "active"


async def test_get_template(db):
    from llm_service.runtime.template_registry import TemplateRegistry

    reg = TemplateRegistry(db)
    tpl_id = await reg.create(
        template_key="extract",
        template_version="v1",
        purpose="Extract entities",
        user_prompt_template="Extract: {{text}}",
        expected_output_type="json_array",
    )
    tpl = await reg.get(tpl_id)
    assert tpl["template_key"] == "extract"


async def test_get_by_key(db):
    from llm_service.runtime.template_registry import TemplateRegistry

    reg = TemplateRegistry(db)
    await reg.create(
        template_key="qa",
        template_version="v1",
        purpose="Q&A",
        user_prompt_template="Answer: {{question}}",
        expected_output_type="text",
    )
    tpl = await reg.get_by_key("qa")
    assert tpl is not None
    assert tpl["template_key"] == "qa"


async def test_list_templates(db):
    from llm_service.runtime.template_registry import TemplateRegistry

    reg = TemplateRegistry(db)
    await reg.create(template_key="a", template_version="v1", purpose="A", user_prompt_template="A", expected_output_type="text")
    await reg.create(template_key="b", template_version="v1", purpose="B", user_prompt_template="B", expected_output_type="text")
    templates = await reg.list_all()
    assert len(templates) == 2


async def test_update_template(db):
    from llm_service.runtime.template_registry import TemplateRegistry

    reg = TemplateRegistry(db)
    tpl_id = await reg.create(
        template_key="update_me",
        template_version="v1",
        purpose="Old purpose",
        user_prompt_template="Old template",
        expected_output_type="text",
    )
    await reg.update(tpl_id, purpose="New purpose")
    tpl = await reg.get(tpl_id)
    assert tpl["purpose"] == "New purpose"


async def test_archive_template(db):
    from llm_service.runtime.template_registry import TemplateRegistry

    reg = TemplateRegistry(db)
    tpl_id = await reg.create(
        template_key="to_archive",
        template_version="v1",
        purpose="Will be archived",
        user_prompt_template="X",
        expected_output_type="text",
    )
    await reg.archive(tpl_id)
    tpl = await reg.get(tpl_id)
    assert tpl["status"] == "archived"
