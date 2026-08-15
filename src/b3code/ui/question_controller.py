"""Estado do card ask_user_question. Esc estaciona. Shift+X dispensa."""

from __future__ import annotations

from textual.events import Key

from b3code.services.chat import ChatService
from b3code.services.questions import OTHER_LABEL, Question
from b3code.ui.widgets.question import QuestionBar


class QuestionController:
    def __init__(self, chat: ChatService, bar: QuestionBar, accent: str) -> None:
        self.awaiting = False
        self.parked = False
        self._chat = chat
        self._bar = bar
        self._accent = accent
        self._items: tuple[Question, ...] = ()
        self._index = 0
        self._picked: list[str] = []

    def set_accent(self, accent: str) -> None:
        self._accent = accent

    def show(self, text: str) -> None:
        self._items = _parse_blocks(text)
        if not self._items:
            return
        self.awaiting = True
        self.parked = False
        self._index = 0
        self._picked = []
        self._paint()

    def consume_key(self, event: Key) -> bool:
        if not self.awaiting:
            return False
        if self.parked:
            return self._unpark(event)
        if self._bar.other_visible():
            return self._other_key(event)
        return self._card_key(event)

    def submit_other(self) -> None:
        text = self._bar.other_text()
        self._bar.hide_other()
        self._accept(text or OTHER_LABEL)

    def leave_other(self) -> None:
        self._bar.hide_other()

    def dismiss(self) -> None:
        self._finish("skipped", dismiss=True)

    def reset(self) -> None:
        self.awaiting = False
        self.parked = False
        self._bar.hide_other()
        self._bar.hide()

    def _card_key(self, event: Key) -> bool:
        if self._nav(event.key) or self._action(event.key):
            event.stop()
            event.prevent_default()
        return True

    def _nav(self, key: str) -> bool:
        step = {"down": 1, "j": 1, "up": -1, "k": -1}.get(key)
        if step is not None:
            self._bar.move(step)
            return True
        wrap = {"tab": 1, "shift+tab": -1}.get(key)
        if wrap is not None:
            self._bar.move(wrap, wrap=True)
            return True
        shift = {"right": 1, "l": 1, "left": -1, "h": -1}.get(key)
        if shift is None:
            return False
        self._shift(shift)
        return True

    def _action(self, key: str) -> bool:
        actions = {
            "z": self._open_other,
            "enter": self._choose,
            "escape": self._park,
            "shift+x": self.dismiss,
        }
        fn = actions.get(key)
        if fn is not None:
            fn()
            return True
        if key.isdigit() and key != "0":
            self._pick_index(int(key) - 1)
            return True
        return False

    def _park(self) -> None:
        self.parked = True

    def _other_key(self, event: Key) -> bool:
        if event.key != "escape":
            return False
        self.leave_other()
        event.stop()
        event.prevent_default()
        return True

    def _unpark(self, event: Key) -> bool:
        if event.key in {"tab", "space"}:
            self.parked = False
            event.stop()
            event.prevent_default()
            return True
        return False

    def _paint(self) -> None:
        item = self._items[self._index]
        self._bar.show_question(item, self._index, len(self._items), self._accent)

    def _shift(self, delta: int) -> None:
        nxt = self._index + delta
        if 0 <= nxt < len(self._items):
            self._index = nxt
            self._paint()

    def _open_other(self) -> None:
        last = len(self._bar._choices) - 1
        self._bar.paint(max(last, 0))
        self._bar.show_other()

    def _choose(self) -> None:
        label = self._bar.current()
        if label == OTHER_LABEL:
            self._open_other()
            return
        self._accept(label)

    def _pick_index(self, idx: int) -> None:
        if 0 <= idx < len(self._bar._choices):
            self._bar.paint(idx)
            self._choose()

    def _accept(self, label: str) -> None:
        self._picked.append(f"{self._items[self._index].question}: {label}")
        if self._index + 1 < len(self._items):
            self._index += 1
            self._paint()
            return
        self._finish("\n".join(self._picked), dismiss=False)

    def _finish(self, text: str, *, dismiss: bool) -> None:
        self.reset()
        if dismiss:
            self._chat.dismiss_question()
            return
        self._chat.answer_question(text)


def _parse_blocks(text: str) -> tuple[Question, ...]:
    from b3code.services.questions import QuestionOption

    blocks = [block.strip() for block in text.split("\n\n") if block.strip()]
    items: list[Question] = []
    for block in blocks:
        lines = block.splitlines()
        if not lines:
            continue
        options = []
        for line in lines[1:]:
            label, _, hint = line.partition(" — ")
            options.append(QuestionOption(label=label.strip(), description=hint.strip()))
        items.append(Question(question=lines[0], options=tuple(options)))
    return tuple(items)
