import os
from pathlib import Path
from app.nodes.base import BaseNode, input_port, output_port, node_info
from app.core.context import ExecutionContext
from app.schemas.node_configs import ReadDirectoryConfig


@node_info(
    display_name="Read Directory",
    category="io",
    color="#059669",
    icon="folder-open",
    description="Scans a folder and filters files by format and/or part of the name."
)

@input_port("path", type_hint="str", required=False, description="Full path to the directory")
@output_port("file_list", type_hint="list")
class ReadDirectoryNode(BaseNode):
    type_name = "read_directory"
    config_model = ReadDirectoryConfig

    async def execute(self, context: ExecutionContext, input_data: dict) -> dict:
        dir_input = context.get_input(self.id, "path")
        dir_path = dir_input if dir_input is not None else self.config.path

        ext = self.config.extension
        name_sub = self.config.name_contains
        is_recursive = self.config.recursive

        target_dir = Path(dir_path)

        if not target_dir.exists() or not target_dir.is_dir():
            await context.log(self.id, f"Directory {dir_path} not found.", level="warning")
            return {"file_list": []}

        found_files = []

        ext_list = [e.strip() for e in ext.split(",")] if ext else []
        name_list = [n.strip() for n in name_sub.split(",")] if name_sub else []

        try:
            if is_recursive:
                for root, dirs, files in os.walk(target_dir):
                    dirs[:] = [d for d in dirs if not d.startswith('.')]

                    for f in files:
                        if f.startswith('.'):
                            continue

                        match_ext = True if not ext_list else any(f.lower().endswith(e.lower()) for e in ext_list)
                        match_name = True if not name_list else any(n.lower() in f.lower() for n in name_list)

                        if match_ext and match_name:
                            full_path = Path(root) / f
                            found_files.append(str(full_path))
            else:
                items = os.listdir(target_dir)
                for f in items:
                    if f.startswith('.'):
                        continue

                    full_path = target_dir / f
                    if not full_path.is_file():
                        continue

                    match_ext = True if not ext_list else any(f.lower().endswith(e.lower()) for e in ext_list)
                    match_name = True if not name_list else any(n.lower() in f.lower() for n in name_list)

                    if match_ext and match_name:
                        found_files.append(str(full_path))

        except PermissionError:
            await context.log(self.id, f"No access to folder {dir_path}", level="error")
            return {"file_list": []}

        return {"file_list": found_files}