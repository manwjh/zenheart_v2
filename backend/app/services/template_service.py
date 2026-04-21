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
