from aiogram.fsm.state import State, StatesGroup


class LeadForm(StatesGroup):
    answering = State()
    confirm = State()
