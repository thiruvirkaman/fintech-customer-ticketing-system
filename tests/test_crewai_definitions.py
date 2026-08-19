from app.ai.contracts import AgentStage, DBAnalysisOutput, ResearchOutput, ValidationOutput
from crewai.llms.base_llm import BaseLLM

from app.ai.crew import CrewAIStageRunner, SupportCrewFactory, create_crewai_llm


class FakeStructuredLLM(BaseLLM):
    def __init__(self, response: str) -> None:
        super().__init__(model="fake-structured", provider="test")
        self.response = response

    def call(
        self,
        messages,
        tools=None,
        callbacks=None,
        available_functions=None,
        from_task=None,
        from_agent=None,
        response_model=None,
    ):
        if response_model is not None:
            return response_model.model_validate_json(self.response)
        return self.response


def test_crewai_research_task_has_required_role_and_structured_output() -> None:
    llm = create_crewai_llm(provider="openai", model="gpt-4o-mini", api_key="test-key")
    crew = SupportCrewFactory(llm).build(
        AgentStage.RESEARCH,
        {"customer_question": "Why is a bank statement needed?", "rag_evidence": []},
    )

    assert crew.process.value == "sequential"
    assert crew.agents[0].role == "LOS Customer Support Research Agent"
    assert crew.tasks[0].output_pydantic is ResearchOutput
    assert not crew.agents[0].allow_delegation


def test_validation_prompt_does_not_include_provisional_score() -> None:
    llm = create_crewai_llm(provider="openai", model="gpt-4o-mini", api_key="test-key")
    crew = SupportCrewFactory(llm).build(
        AgentStage.VALIDATION,
        {
            "customer_question": "Question",
            "proposed_answer": {
                "draft_answer": "Answer",
                "provisional_confidence": 99,
            },
        },
    )

    assert crew.tasks[0].output_pydantic is ValidationOutput
    assert "provisional_confidence" not in crew.tasks[0].description


def test_ollama_llm_is_explicitly_configurable() -> None:
    llm = create_crewai_llm(
        provider="ollama",
        model="glm-5.2:cloud",
        api_key="test-key",
        base_url="https://ollama.com",
    )

    assert llm.provider == "ollama"
    assert llm.model == "glm-5.2:cloud"
    assert llm.base_url == "https://ollama.com/v1"


def test_db_agent_reasons_only_over_supplied_allowlisted_facts() -> None:
    llm = create_crewai_llm(provider="openai", model="gpt-4o-mini", api_key="test-key")
    crew = SupportCrewFactory(llm).build(
        AgentStage.DB,
        {"customer_question": "What is my status?", "db_tool_results": [{"status": "PENDING"}]},
    )

    assert crew.agents[0].role == "LOS Data Specialist"
    assert crew.tasks[0].output_pydantic is DBAnalysisOutput
    assert "Never propose INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE" in crew.tasks[0].description


def test_semantic_guardrails_are_explicit_bounded_stages() -> None:
    llm = create_crewai_llm(provider="openai", model="gpt-4o-mini", api_key="test-key")
    factory = SupportCrewFactory(llm)

    input_crew = factory.build(AgentStage.INPUT_GUARDRAIL, {"email": {"body": "hello"}})
    output_crew = factory.build(AgentStage.OUTPUT_GUARDRAIL, {"candidate_email": {"body": "hello"}})

    assert input_crew.agents[0].max_iter == 3
    assert output_crew.agents[0].max_iter == 3


def test_real_crewai_kickoff_returns_validated_structured_output_without_network() -> None:
    fake_llm = FakeStructuredLLM(
        '{"intent":"GENERAL","draft_answer":"Grounded answer",'
        '"evidence_ids":["EV-1"],"unknowns":[],"provisional_confidence":80}'
    )
    runner = CrewAIStageRunner(SupportCrewFactory(fake_llm))

    result = runner.run(
        AgentStage.RESEARCH,
        {"customer_question": "Question", "rag_evidence": [{"evidence_id": "EV-1"}]},
    )

    assert isinstance(result, ResearchOutput)
    assert result.evidence_ids == ["EV-1"]
