import pytest
from algodesk.models import State
from algodesk.state_machine import TradeStateMachine, IllegalTransition

def test_legal_transitions():
    sm = TradeStateMachine()
    assert sm.state == State.FLAT
    
    sm.transition(State.SIGNAL)
    assert sm.state == State.SIGNAL
    
    sm.transition(State.IN_POSITION)
    assert sm.state == State.IN_POSITION
    
    sm.transition(State.PARTIAL_EXIT)
    assert sm.state == State.PARTIAL_EXIT
    
    sm.transition(State.FLAT)
    assert sm.state == State.FLAT

def test_illegal_transition():
    sm = TradeStateMachine()
    # Cannot go from FLAT straight to PARTIAL_EXIT
    with pytest.raises(IllegalTransition):
        sm.transition(State.PARTIAL_EXIT)