import pytest
from langchain_core.tools import BaseTool
from langchain_core.messages import AIMessage, ToolMessage
from forum.tools import build_tools, memory_search_tool
from forum.claude import AgentError, checkpoint_messages


@pytest.mark.asyncio
async def test_decorated_tools_capture_state_and_enforce_dependencies():
    class Coordinator:
        def available(self, state):
            return ['build_affirmative']
        async def execute(self, name, state, emit):
            state['called'] = name
            return {'done': True}
    state = {}
    registry = build_tools(Coordinator(), state, None)
    assert all(isinstance(action, BaseTool) for action in registry.values())
    assert set(registry['build_affirmative'].args) == {'explanation'}
    assert await registry['build_affirmative'].ainvoke({'explanation': 'Start'}) == {'done': True}
    assert state['called'] == 'build_affirmative'
    with pytest.raises(AgentError, match='prerequisites'):
        await registry['judge_debate'].ainvoke({'explanation': 'Skip ahead'})
    assert await registry['handoff_to_human'].ainvoke({'explanation': 'Clarify', 'question': 'Which country?'}) == {'reason': 'Clarify', 'question': 'Which country?'}


@pytest.mark.asyncio
async def test_memory_search_is_a_langchain_tool():
    class Memory:
        def search(self, resolution):
            return [{'resolution': resolution}]
    action = memory_search_tool(Memory())
    assert isinstance(action, BaseTool)
    assert await action.ainvoke({'resolution': 'School uniforms'}) == [{'resolution': 'School uniforms'}]


def test_existing_checkpoint_history_becomes_langchain_messages():
    messages = checkpoint_messages([
        {'role': 'assistant', 'content': [{'type': 'tool_use', 'id': 'old_1', 'name': 'build_affirmative', 'input': {'explanation': 'Start'}}]},
        {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'old_1', 'content': 'done'}]},
    ], 'Coordinate')
    assert isinstance(messages[1], AIMessage)
    assert messages[1].tool_calls[0]['id'] == 'old_1'
    assert isinstance(messages[2], ToolMessage)
    assert messages[2].tool_call_id == 'old_1'
