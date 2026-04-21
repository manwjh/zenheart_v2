import random
import string
from pathlib import Path
from typing import Union

from jinja2 import Environment, FileSystemLoader


class TemplateService:
    def __init__(self, template_path: Union[str, Path]):
        self.template_path = Path(template_path)
        if not self.template_path.is_dir():
            raise RuntimeError(f"Mail template directory not found: {self.template_path}")
        self.env = Environment(
            loader=FileSystemLoader(str(self.template_path)),
            autoescape=True,
        )

    def render_template(self, template_name: str, **context: object) -> str:
        return self.env.get_template(template_name).render(**context)

    @staticmethod
    def generate_verification_code(length: int = 6, code_type: str = "numeric") -> str:
        if code_type == "numeric":
            return "".join(random.choices(string.digits, k=length))
        if code_type == "alphanumeric":
            return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))
        return "".join(random.choices(string.ascii_letters + string.digits, k=length))
