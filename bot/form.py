import tomllib
from dataclasses import dataclass

TYPES = {"text", "phone", "choice", "number", "file"}


class FormError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Question:
    key: str
    type: str
    text: str
    label: str
    required: bool = True
    options: tuple[str, ...] = ()
    min: float | None = None
    max: float | None = None
    min_length: int = 1
    max_length: int = 500


@dataclass(frozen=True, slots=True)
class Form:
    title: str
    intro: str
    done: str
    questions: tuple[Question, ...]

    @property
    def labels(self) -> list[str]:
        return [q.label for q in self.questions]


def load_form(path: str, reserved: set[str] = frozenset()) -> Form:
    """Загружает анкету из TOML. reserved — тексты служебных кнопок, которые нельзя использовать как варианты."""
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError:
        raise FormError(f"Файл анкеты не найден: {path}") from None
    except tomllib.TOMLDecodeError as e:
        raise FormError(f"{path}: ошибка синтаксиса TOML: {e}") from None

    questions: list[Question] = []
    keys: set[str] = set()
    for i, q in enumerate(raw.get("questions", []), 1):
        where = f"{path}, вопрос №{i}"
        key, text, type_ = q.get("key"), q.get("text"), q.get("type", "text")
        if not key or not text:
            raise FormError(f"{where}: обязательны поля key и text")
        if key in keys:
            raise FormError(f"{where}: повторяющийся key «{key}»")
        if type_ not in TYPES:
            raise FormError(f"{where}: неизвестный type «{type_}», допустимы: {', '.join(sorted(TYPES))}")
        options = tuple(str(o) for o in q.get("options", ()))
        if type_ == "choice":
            if not options:
                raise FormError(f"{where}: для choice нужен список options")
            if any(not o or len(o) > 60 or o in reserved for o in options):
                raise FormError(f"{where}: варианты должны быть 1–60 символов и не совпадать со служебными кнопками")
        keys.add(key)
        questions.append(
            Question(
                key=key,
                type=type_,
                text=text,
                label=q.get("label", key),
                required=bool(q.get("required", True)),
                options=options,
                min=q.get("min"),
                max=q.get("max"),
                min_length=int(q.get("min_length", 1)),
                max_length=int(q.get("max_length", 500)),
            )
        )
    if not questions:
        raise FormError(f"{path}: в анкете нет вопросов")
    return Form(
        title=raw.get("title", "Заявка"),
        intro=raw.get("intro", ""),
        done=raw.get("done", "Спасибо! Мы скоро свяжемся с вами."),
        questions=tuple(questions),
    )
