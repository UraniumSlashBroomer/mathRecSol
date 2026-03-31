import sys
import json
import shutil
import html
import re
from pathlib import Path

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QPixmap
    from PyQt6.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFileDialog,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QSizePolicy,
        QStackedLayout,
        QTextBrowser,
        QTextEdit,
        QTreeWidget,
        QTreeWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError:
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QPixmap
    from PyQt5.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFileDialog,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QSizePolicy,
        QStackedLayout,
        QTextBrowser,
        QTextEdit,
        QTreeWidget,
        QTreeWidgetItem,
        QVBoxLayout,
        QWidget,
    )

from easyocr_service import EasyOcrService
from nanonets_ocr2_service import NanonetsOcr2Service

try:
    import markdown as markdown_lib
except ImportError:
    markdown_lib = None

USER_ROLE = getattr(Qt, "ItemDataRole", Qt).UserRole
EDITABLE_FLAG = getattr(Qt, "ItemFlag", Qt).ItemIsEditable
DRAG_ENABLED_FLAG = getattr(Qt, "ItemFlag", Qt).ItemIsDragEnabled
DROP_ENABLED_FLAG = getattr(Qt, "ItemFlag", Qt).ItemIsDropEnabled
ITEM_TYPE_FOLDER = "folder"
ITEM_TYPE_PROBLEM = "problem"


class MoveCancelledError(Exception):
    pass


def render_markdown_html(text: str) -> str:
    if markdown_lib is not None:
        return markdown_lib.markdown(
            text,
            extensions=["fenced_code", "tables", "nl2br", "sane_lists"],
        )

    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped, flags=re.DOTALL)
    escaped = re.sub(r"\*(.+?)\*", r"<em>\1</em>", escaped, flags=re.DOTALL)
    escaped = re.sub(r"^### (.+)$", r"<h3>\1</h3>", escaped, flags=re.MULTILINE)
    escaped = re.sub(r"^## (.+)$", r"<h2>\1</h2>", escaped, flags=re.MULTILINE)
    escaped = re.sub(r"^# (.+)$", r"<h1>\1</h1>", escaped, flags=re.MULTILINE)
    paragraphs = [paragraph.replace("\n", "<br>") for paragraph in escaped.split("\n\n")]
    return "".join(f"<p>{paragraph}</p>" for paragraph in paragraphs if paragraph.strip())


class ProblemTreeWidget(QTreeWidget):
    def __init__(self, controller: "MathOcrApp") -> None:
        super().__init__()
        self.controller = controller

    def dropEvent(self, event) -> None:
        super().dropEvent(event)
        self.controller.handle_tree_drop()


class UploadPreviewDialog(QDialog):
    def __init__(self, controller: "MathOcrApp", image_path: str, default_folder: str) -> None:
        super().__init__(controller)
        self.controller = controller
        self.image_path = image_path
        self.recognized_text = ""

        self.setWindowTitle("Save image")
        self.resize(960, 640)

        main_layout = QVBoxLayout(self)
        top_layout = QHBoxLayout()
        right_layout = QVBoxLayout()

        self.preview_label = QLabel("No preview available")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(380, 380)
        self.preview_label.setStyleSheet("border: 1px solid #999; background: #f5f5f5;")

        self.folder_combo = QComboBox()
        self.folder_combo.setEditable(True)
        self.folder_combo.addItems(self.controller.storage_folder_labels())
        self.folder_combo.setCurrentText(default_folder)
        completer = self.folder_combo.completer()
        if completer is not None:
            completer.setCaseSensitivity(getattr(Qt, "CaseSensitivity", Qt).CaseInsensitive)

        self.recognize_button = QPushButton("Recognize image")
        self.recognize_button.clicked.connect(self.recognize_image)

        self.dialog_status_label = QLabel("Status: ready to save")
        self.dialog_status_label.setWordWrap(True)

        self.recognized_output = QTextBrowser()
        self.recognized_output.setPlaceholderText("Recognized text preview will appear here.")

        right_layout.addWidget(QLabel("Save to folder"))
        right_layout.addWidget(self.folder_combo)
        right_layout.addWidget(self.recognize_button)
        right_layout.addWidget(self.dialog_status_label)
        right_layout.addWidget(QLabel("Recognized text preview"))
        right_layout.addWidget(self.recognized_output, 1)

        top_layout.addWidget(self.preview_label, 1)
        top_layout.addLayout(right_layout, 1)
        main_layout.addLayout(top_layout)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        main_layout.addWidget(self.button_box)

        self._update_preview()

    def _update_preview(self) -> None:
        pixmap = QPixmap(self.image_path)
        if pixmap.isNull():
            return

        scaled = pixmap.scaled(
            self.preview_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_preview()

    def recognize_image(self) -> None:
        if not self.controller.ensure_ocr_model_loaded():
            self.dialog_status_label.setText("Status: load an OCR model first")
            return

        self.dialog_status_label.setText("Status: running OCR")
        QApplication.processEvents()

        try:
            self.recognized_text = self.controller.ocr_service.read_text(self.image_path)
        except Exception as exc:
            QMessageBox.critical(self, "OCR failed", str(exc))
            self.dialog_status_label.setText("Status: OCR failed")
            return

        self.recognized_output.setMarkdown(self.recognized_text or "")
        self.dialog_status_label.setText("Status: OCR completed")

    def selected_folder_label(self) -> str:
        return self.folder_combo.currentText().strip() or "/"

    def accept(self) -> None:
        folder_path = self.controller.folder_label_to_path(self.selected_folder_label())
        if folder_path is None:
            QMessageBox.warning(self, "Invalid folder", "Choose an existing folder from storage.")
            return

        super().accept()


class ConflictResolutionDialog(QDialog):
    def __init__(self, parent: QWidget, item_type: str, item_name: str, destination_label: str) -> None:
        super().__init__(parent)
        self.choice = "cancel"
        self.setWindowTitle("Name conflict")

        layout = QVBoxLayout(self)
        label = "Folder" if item_type == ITEM_TYPE_FOLDER else "Task"
        layout.addWidget(QLabel(f"{label} '{item_name}' already exists."))
        layout.addWidget(QLabel(f"Target: {destination_label}"))

        buttons_layout = QHBoxLayout()
        self.overwrite_button = QPushButton("Overwrite")
        self.rename_button = QPushButton("Rename current item")
        self.cancel_button = QPushButton("Cancel")

        self.overwrite_button.clicked.connect(self._choose_overwrite)
        self.rename_button.clicked.connect(self._choose_rename)
        self.cancel_button.clicked.connect(self.reject)

        buttons_layout.addWidget(self.overwrite_button)
        buttons_layout.addWidget(self.rename_button)
        buttons_layout.addWidget(self.cancel_button)
        layout.addLayout(buttons_layout)

    def _choose_overwrite(self) -> None:
        self.choice = "overwrite"
        self.accept()

    def _choose_rename(self) -> None:
        self.choice = "rename"
        self.accept()


class MarkdownTextEdit(QTextEdit):
    def __init__(self, commit_callback) -> None:
        super().__init__()
        self.commit_callback = commit_callback

    def keyPressEvent(self, event) -> None:
        key_enter = getattr(Qt, "Key", Qt).Key_Return
        key_enter_alt = getattr(Qt, "Key", Qt).Key_Enter
        modifiers = getattr(Qt, "KeyboardModifier", Qt)
        if event.key() in (key_enter, key_enter_alt) and event.modifiers() == modifiers.ShiftModifier:
            self.commit_callback()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        self.commit_callback()
        super().focusOutEvent(event)


class MarkdownPreviewWidget(QTextBrowser):
    def __init__(self, edit_callback) -> None:
        super().__init__()
        self.edit_callback = edit_callback
        self.setOpenExternalLinks(True)

    def mouseDoubleClickEvent(self, event) -> None:
        self.edit_callback()
        super().mouseDoubleClickEvent(event)


class MarkdownDisplayWidget(QWidget):
    def __init__(self, save_callback) -> None:
        super().__init__()
        self.save_callback = save_callback
        self.markdown_text = ""

        layout = QStackedLayout(self)
        self.preview_widget = MarkdownPreviewWidget(self.start_editing)
        self.editor_widget = MarkdownTextEdit(self.commit_edits)
        self.editor_widget.setPlaceholderText("Double click preview to edit. Shift+Enter to render markdown.")
        layout.addWidget(self.preview_widget)
        layout.addWidget(self.editor_widget)
        self.layout_stack = layout
        self.layout_stack.setCurrentWidget(self.preview_widget)
        self._render_markdown("")

    def set_markdown_text(self, text: str) -> None:
        self.markdown_text = text or ""
        self.editor_widget.setPlainText(self.markdown_text)
        self._render_markdown(self.markdown_text)
        self.layout_stack.setCurrentWidget(self.preview_widget)

    def start_editing(self) -> None:
        self.editor_widget.setPlainText(self.markdown_text)
        self.layout_stack.setCurrentWidget(self.editor_widget)
        self.editor_widget.setFocus()

    def commit_edits(self) -> None:
        self.markdown_text = self.editor_widget.toPlainText()
        self._render_markdown(self.markdown_text)
        self.layout_stack.setCurrentWidget(self.preview_widget)
        self.save_callback()

    def commit_if_editing(self) -> None:
        if self.layout_stack.currentWidget() is self.editor_widget:
            self.commit_edits()

    def _render_markdown(self, text: str) -> None:
        body_html = render_markdown_html(text or "")
        self.preview_widget.setHtml(body_html)


class MathOcrApp(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.ocr_services = {
            "easyOCR": EasyOcrService(),
            "nanonets-OCR2": NanonetsOcr2Service(),
        }
        self.ocr_service = None
        self.selected_ocr_model_name = None
        self.selected_image_path = None
        self.selected_problem_dir = None
        self.problems_dir = Path(__file__).resolve().parent / "problems"
        self.is_updating_problem_tree = False
        self.is_loading_problem_text = False

        self.setWindowTitle("Math OCR Desktop App")
        self.resize(1100, 720)

        self._build_ui()
        self._load_problem_tree()

    def _build_ui(self) -> None:
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout()
        top_buttons_layout = QHBoxLayout()
        content_layout = QHBoxLayout()
        left_panel_layout = QVBoxLayout()
        right_panel_layout = QVBoxLayout()

        self.load_model_button = QPushButton("Upload OCR model")
        self.load_model_button.clicked.connect(self.load_model)

        self.upload_image_button = QPushButton("Upload image")
        self.upload_image_button.clicked.connect(self.upload_image)

        self.solve_button = QPushButton("Run OCR")
        self.solve_button.clicked.connect(self.run_ocr)

        top_buttons_layout.addWidget(self.load_model_button)
        top_buttons_layout.addWidget(self.upload_image_button)
        top_buttons_layout.addWidget(self.solve_button)

        self.status_label = QLabel("Status: waiting for model and image")
        self.status_label.setWordWrap(True)

        self.image_label = QLabel("No image selected")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(420, 420)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image_label.setStyleSheet("border: 1px solid #999; background: #f5f5f5;")

        self.image_path_label = QLabel("Image: not selected")
        self.image_path_label.setWordWrap(True)

        tree_actions_layout = QHBoxLayout()

        self.create_folder_button = QPushButton("+")
        self.create_folder_button.setFixedWidth(32)
        self.create_folder_button.setToolTip("Create folder")
        self.create_folder_button.clicked.connect(self.create_folder)

        self.delete_button = QPushButton("x")
        self.delete_button.setFixedWidth(32)
        self.delete_button.setToolTip("Delete selected item")
        self.delete_button.clicked.connect(self.delete_selected_item)

        tree_actions_layout.addWidget(self.create_folder_button)
        tree_actions_layout.addWidget(self.delete_button)
        tree_actions_layout.addStretch()

        self.problem_tree = ProblemTreeWidget(self)
        self.problem_tree.setHeaderHidden(True)
        self.problem_tree.itemClicked.connect(self.handle_tree_item_click)
        self.problem_tree.itemChanged.connect(self.rename_tree_item)
        self.problem_tree.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self.problem_tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.problem_tree.setDefaultDropAction(getattr(Qt, "DropAction", Qt).MoveAction)
        self.problem_tree.setDragEnabled(True)
        self.problem_tree.setAcceptDrops(True)
        self.problem_tree.setDropIndicatorShown(True)

        self.ocr_output = MarkdownDisplayWidget(self.save_recognized_text_edits)
        self.llm_output = MarkdownDisplayWidget(self.save_llm_text_edits)

        left_panel_layout.addWidget(QLabel("My math problems"))
        left_panel_layout.addLayout(tree_actions_layout)
        left_panel_layout.addWidget(self.problem_tree)

        right_panel_layout.addWidget(self.image_label, 3)
        right_panel_layout.addWidget(QLabel("Recognized text"))
        right_panel_layout.addWidget(self.ocr_output)
        right_panel_layout.addWidget(QLabel("LLM solution"))
        right_panel_layout.addWidget(self.llm_output)

        content_layout.addLayout(left_panel_layout, 1)
        content_layout.addLayout(right_panel_layout, 2)

        main_layout.addLayout(top_buttons_layout)
        main_layout.addWidget(self.status_label)
        main_layout.addWidget(self.image_path_label)
        main_layout.addLayout(content_layout)

        central_widget.setLayout(main_layout)

    def load_model(self) -> None:
        model_names = list(self.ocr_services.keys())
        current_index = model_names.index(self.selected_ocr_model_name) if self.selected_ocr_model_name in model_names else 0
        model_name, confirmed = QInputDialog.getItem(
            self,
            "Select OCR model",
            "OCR model:",
            model_names,
            current_index,
            False,
        )
        if not confirmed:
            return

        self.status_label.setText(f"Status: loading {model_name}")
        QApplication.processEvents()

        try:
            self.ocr_service = self.ocr_services[model_name]
            if not self.ocr_service.is_loaded():
                self.ocr_service.load()
        except Exception as exc:
            QMessageBox.critical(self, "Model loading failed", str(exc))
            self.status_label.setText("Status: model loading failed")
            return

        self.selected_ocr_model_name = model_name
        self.status_label.setText(f"Status: {model_name} loaded")

    def ensure_ocr_model_loaded(self) -> bool:
        if self.ocr_service is not None and self.ocr_service.is_loaded():
            return True

        standard_button = getattr(QMessageBox, "StandardButton", QMessageBox)
        answer = QMessageBox.question(
            self,
            "Model not loaded",
            "OCR model is not loaded. Load it now?",
        )
        if answer != standard_button.Yes:
            return False

        self.load_model()
        return self.ocr_service is not None and self.ocr_service.is_loaded()

    def upload_image(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)",
        )

        if not file_path:
            return

        default_folder = self.path_to_folder_label(self._selected_container_dir())
        preview_dialog = UploadPreviewDialog(self, file_path, default_folder)
        dialog_code = getattr(QDialog, "DialogCode", QDialog)
        if preview_dialog.exec() != dialog_code.Accepted:
            return

        target_parent_dir = self.folder_label_to_path(preview_dialog.selected_folder_label())
        if target_parent_dir is None:
            QMessageBox.warning(self, "Invalid folder", "Choose an existing folder from storage.")
            return

        self._save_uploaded_image(file_path, target_parent_dir, preview_dialog.recognized_text)

    def _update_image_preview(self, image_path: str) -> None:
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            self.image_label.setText("Unable to preview this image")
            return

        scaled = pixmap.scaled(
            self.image_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.selected_image_path:
            self._update_image_preview(self.selected_image_path)

    def run_ocr(self) -> None:
        if self.ocr_service is None or not self.ocr_service.is_loaded():
            QMessageBox.warning(self, "Model not loaded", "Load the OCR model first.")
            return

        if not self.selected_image_path:
            QMessageBox.warning(self, "Image not selected", "Upload an image first.")
            return

        self.status_label.setText("Status: running OCR")
        QApplication.processEvents()

        try:
            recognized_text = self.ocr_service.read_text(self.selected_image_path)
        except Exception as exc:
            QMessageBox.critical(self, "OCR failed", str(exc))
            self.status_label.setText("Status: OCR failed")
            return

        self._set_markdown(self.ocr_output, recognized_text)
        self._save_problem(self.selected_image_path, recognized_text)
        self.status_label.setText("Status: OCR completed")

    def _save_problem(self, image_path: str, recognized_text: str) -> None:
        problem_dir = Path(image_path).parent
        if not problem_dir.exists():
            return

        problem_data = self._read_problem_data(problem_dir)
        problem_data["recognized_text"] = recognized_text
        self._write_problem_data(problem_dir, problem_data)
        self._refresh_problem_tree()

    def _save_uploaded_image(self, file_path: str, target_parent_dir: Path, recognized_text: str) -> None:
        image_name = Path(file_path).name
        problem_title = self._display_title(image_name)
        problem_dir = target_parent_dir / problem_title
        if problem_dir.exists():
            QMessageBox.warning(
                self,
                "Duplicate image",
                f"A math problem named '{problem_title}' already exists in this folder.",
            )
            return

        self.problems_dir.mkdir(parents=True, exist_ok=True)
        stored_image_path = problem_dir / image_name
        problem_dir.mkdir(parents=True, exist_ok=False)
        shutil.copy2(file_path, stored_image_path)

        problem_data = {
            "title": problem_title,
            "image_path": str(stored_image_path),
            "recognized_text": recognized_text,
            "llm_text": "",
        }
        self._write_problem_data(problem_dir, problem_data)
        self._refresh_problem_tree()

        self.selected_image_path = str(stored_image_path)
        self.selected_problem_dir = problem_dir
        self.image_path_label.setText(f"Image: {self._storage_relative_label(stored_image_path)}")
        self._set_markdown(self.ocr_output, recognized_text)
        self._set_markdown(self.llm_output, "")
        self.status_label.setText("Status: image saved to problems storage")
        self._update_image_preview(str(stored_image_path))

    def _problem_data_path(self, problem_dir: Path) -> Path:
        return problem_dir / "data.json"

    def _find_problem_image_path(self, problem_dir: Path) -> str:
        image_candidates = sorted(
            (
                path for path in problem_dir.iterdir()
                if path.is_file() and path.name != "data.json"
            ),
            key=lambda path: path.name.lower(),
        )
        if image_candidates:
            return str(image_candidates[0])
        return str(problem_dir / problem_dir.name)

    def _write_problem_data(self, problem_dir: Path, problem_data: dict) -> None:
        data_path = self._problem_data_path(problem_dir)
        with data_path.open("w", encoding="utf-8") as file:
            json.dump(problem_data, file, ensure_ascii=False, indent=2)

    def _read_problem_data(self, problem_dir: Path) -> dict:
        data_path = self._problem_data_path(problem_dir)
        if not data_path.exists():
            return {
                "title": self._display_title(problem_dir.name),
                "image_path": self._find_problem_image_path(problem_dir),
                "recognized_text": "",
                "llm_text": "",
            }

        with data_path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        data.setdefault("title", self._display_title(problem_dir.name))
        data.setdefault("image_path", self._find_problem_image_path(problem_dir))
        data.setdefault("recognized_text", "")
        data.setdefault("llm_text", "")
        return data

    def _refresh_problem_tree(self) -> None:
        self.is_updating_problem_tree = True
        self.problem_tree.clear()
        self._load_problem_tree()
        self.is_updating_problem_tree = False

    def _load_problem_tree(self) -> None:
        self.problems_dir.mkdir(parents=True, exist_ok=True)
        self._populate_tree_branch(self.problems_dir, self.problem_tree.invisibleRootItem())
        self.problem_tree.expandAll()

    def _populate_tree_branch(self, parent_dir: Path, parent_item: QTreeWidgetItem) -> None:
        child_dirs = sorted((path for path in parent_dir.iterdir() if path.is_dir()), key=lambda path: path.name.lower())
        folder_dirs = [path for path in child_dirs if not self._problem_data_path(path).exists()]
        problem_dirs = [path for path in child_dirs if self._problem_data_path(path).exists()]

        for folder_dir in folder_dirs:
            folder_item = QTreeWidgetItem([folder_dir.name])
            folder_item.setData(0, USER_ROLE, {"type": ITEM_TYPE_FOLDER, "path": str(folder_dir)})
            folder_item.setFlags(folder_item.flags() | EDITABLE_FLAG | DRAG_ENABLED_FLAG | DROP_ENABLED_FLAG)
            parent_item.addChild(folder_item)
            self._populate_tree_branch(folder_dir, folder_item)

        for problem_dir in problem_dirs:
            problem_data = self._read_problem_data(problem_dir)
            problem_item = QTreeWidgetItem([self._display_title(problem_data.get("title", problem_dir.name))])
            problem_item.setData(
                0,
                USER_ROLE,
                {"type": ITEM_TYPE_PROBLEM, "path": str(problem_dir), "problem_data": problem_data},
            )
            problem_item.setFlags((problem_item.flags() | EDITABLE_FLAG | DRAG_ENABLED_FLAG) & ~DROP_ENABLED_FLAG)
            parent_item.addChild(problem_item)

    def handle_tree_item_click(self, item: QTreeWidgetItem) -> None:
        self.commit_open_markdown_edits()
        item_data = item.data(0, USER_ROLE) or {}
        if item_data.get("type") != ITEM_TYPE_PROBLEM:
            self.status_label.setText("Status: folder selected")
            return

        problem_dir = Path(item_data.get("path", ""))
        problem_data = self._read_problem_data(problem_dir)
        item_data["problem_data"] = problem_data
        item.setData(0, USER_ROLE, item_data)
        image_path = problem_data.get("image_path", "")
        recognized_text = problem_data.get("recognized_text", "")
        llm_text = problem_data.get("llm_text", "")
        self.selected_image_path = image_path
        self.selected_problem_dir = Path(image_path).parent if image_path else None
        self.image_path_label.setText(f"Image: {self._storage_relative_label(image_path)}")
        self._update_image_preview(image_path)
        self._set_markdown(self.ocr_output, recognized_text)
        self._set_markdown(self.llm_output, llm_text)
        self.status_label.setText("Status: loaded saved math problem")

    def rename_tree_item(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0 or self.is_updating_problem_tree:
            return

        item_data = item.data(0, USER_ROLE) or {}
        item_type = item_data.get("type")
        try:
            if item_type == ITEM_TYPE_FOLDER:
                self._rename_folder_item(item, item_data)
            elif item_type == ITEM_TYPE_PROBLEM:
                self._rename_problem_item(item, item_data)
        except Exception as exc:
            self._refresh_problem_tree()
            QMessageBox.critical(self, "Rename failed", str(exc))

    def handle_tree_drop(self) -> None:
        try:
            self._sync_tree_to_storage(self.problem_tree.invisibleRootItem(), self.problems_dir)
        except MoveCancelledError:
            self._refresh_problem_tree()
            self.status_label.setText("Status: move cancelled")
            return
        except Exception as exc:
            self._refresh_problem_tree()
            QMessageBox.critical(self, "Move failed", str(exc))
            return

        self._refresh_problem_tree()
        self.status_label.setText("Status: storage reorganized")

    def _set_markdown(self, widget, text: str) -> None:
        self.is_loading_problem_text = True
        widget.set_markdown_text(text or "")
        self.is_loading_problem_text = False

    def _storage_relative_label(self, path: str | Path) -> str:
        path_obj = Path(path)
        try:
            return path_obj.relative_to(self.problems_dir).as_posix()
        except ValueError:
            return str(path_obj)

    def _display_title(self, title: str) -> str:
        if "." not in title:
            return title
        return title.rsplit(".", 1)[0]

    def _selected_container_dir(self) -> Path:
        item = self.problem_tree.currentItem()
        if item is None:
            return self.problems_dir

        item_data = item.data(0, USER_ROLE) or {}
        item_type = item_data.get("type")
        item_path = Path(item_data.get("path", self.problems_dir))
        if item_type == ITEM_TYPE_FOLDER:
            return item_path
        if item_type == ITEM_TYPE_PROBLEM:
            return item_path.parent
        return self.problems_dir

    def commit_open_markdown_edits(self) -> None:
        self.ocr_output.commit_if_editing()
        self.llm_output.commit_if_editing()

    def _update_current_tree_problem_data(self, problem_data: dict) -> None:
        current_item = self.problem_tree.currentItem()
        if current_item is None:
            return

        item_data = current_item.data(0, USER_ROLE) or {}
        if item_data.get("type") != ITEM_TYPE_PROBLEM:
            return

        item_data["problem_data"] = problem_data
        current_item.setData(0, USER_ROLE, item_data)

    def storage_folder_labels(self) -> list[str]:
        self.problems_dir.mkdir(parents=True, exist_ok=True)
        labels = ["/"]
        for folder_dir in sorted(self._iter_storage_folders(self.problems_dir), key=lambda path: str(path).lower()):
            labels.append(self.path_to_folder_label(folder_dir))
        return labels

    def _iter_storage_folders(self, root_dir: Path):
        for child_dir in root_dir.iterdir():
            if not child_dir.is_dir():
                continue
            if self._problem_data_path(child_dir).exists():
                continue
            yield child_dir
            yield from self._iter_storage_folders(child_dir)

    def path_to_folder_label(self, folder_path: Path) -> str:
        try:
            relative_path = folder_path.relative_to(self.problems_dir)
        except ValueError:
            return "/"

        if str(relative_path) == ".":
            return "/"
        return relative_path.as_posix()

    def folder_label_to_path(self, folder_label: str) -> Path | None:
        normalized = folder_label.strip() or "/"
        if normalized == "/":
            return self.problems_dir

        target_path = (self.problems_dir / normalized).resolve()
        try:
            target_path.relative_to(self.problems_dir.resolve())
        except ValueError:
            return None

        if not target_path.exists() or not target_path.is_dir():
            return None
        if self._problem_data_path(target_path).exists():
            return None
        return target_path

    def create_folder(self) -> None:
        folder_name, confirmed = QInputDialog.getText(self, "Create folder", "Folder name:")
        if not confirmed:
            return

        folder_name = folder_name.strip()
        if not folder_name:
            QMessageBox.warning(self, "Invalid name", "Folder name cannot be empty.")
            return

        parent_dir = self._selected_container_dir()
        new_folder_dir = parent_dir / folder_name
        if new_folder_dir.exists():
            QMessageBox.warning(self, "Duplicate name", f"A folder named '{folder_name}' already exists.")
            return

        new_folder_dir.mkdir(parents=True, exist_ok=False)
        self._refresh_problem_tree()
        self.status_label.setText("Status: folder created")

    def save_recognized_text_edits(self) -> None:
        self._save_selected_problem_field("recognized_text", self.ocr_output.markdown_text)

    def save_llm_text_edits(self) -> None:
        self._save_selected_problem_field("llm_text", self.llm_output.markdown_text)

    def _save_selected_problem_field(self, field_name: str, field_value: str) -> None:
        if self.is_loading_problem_text or self.selected_problem_dir is None:
            return

        problem_data = self._read_problem_data(self.selected_problem_dir)
        problem_data[field_name] = field_value
        self._write_problem_data(self.selected_problem_dir, problem_data)
        self._update_current_tree_problem_data(problem_data)

    def delete_selected_item(self) -> None:
        item = self.problem_tree.currentItem()
        if item is None:
            QMessageBox.warning(self, "Nothing selected", "Select a folder or task to delete.")
            return

        item_data = item.data(0, USER_ROLE) or {}
        item_path = Path(item_data.get("path", ""))
        if not item_path.exists():
            return

        item_type = item_data.get("type")
        label = "folder" if item_type == ITEM_TYPE_FOLDER else "task"
        standard_button = getattr(QMessageBox, "StandardButton", QMessageBox)
        answer = QMessageBox.question(
            self,
            "Delete item",
            f"Delete this {label}: '{item.text(0)}'?",
        )
        if answer != standard_button.Yes:
            return

        if self.selected_problem_dir and (item_path == self.selected_problem_dir or item_path in self.selected_problem_dir.parents):
            self.selected_problem_dir = None
            self.selected_image_path = None
            self.image_label.clear()
            self.image_label.setText("No image selected")
            self.image_path_label.setText("Image: not selected")
            self._set_markdown(self.ocr_output, "")
            self._set_markdown(self.llm_output, "")

        shutil.rmtree(item_path)
        self._refresh_problem_tree()
        self.status_label.setText("Status: item deleted")

    def _rename_folder_item(self, item: QTreeWidgetItem, item_data: dict) -> None:
        old_folder_dir = Path(item_data["path"])
        old_name = old_folder_dir.name
        new_name = item.text(0).strip()
        if new_name == old_name:
            return

        if not new_name:
            self._restore_tree_item_text(item, old_name)
            QMessageBox.warning(self, "Invalid name", "Folder name cannot be empty.")
            return

        new_folder_dir = old_folder_dir.parent / new_name
        if new_folder_dir.exists():
            self._restore_tree_item_text(item, old_name)
            QMessageBox.warning(self, "Duplicate name", f"A folder named '{new_name}' already exists.")
            return

        old_selected_problem_dir = self.selected_problem_dir
        old_selected_image_path = self.selected_image_path
        old_folder_dir.rename(new_folder_dir)
        self._rewrite_problem_paths_in_tree(new_folder_dir)

        item_data["path"] = str(new_folder_dir)
        item.setData(0, USER_ROLE, item_data)
        self._update_selected_paths_after_move(old_folder_dir, new_folder_dir, old_selected_problem_dir, old_selected_image_path)
        self._refresh_problem_tree()
        self.status_label.setText("Status: folder renamed")

    def _resolve_move_conflict(self, item_name: str, desired_path: Path, item_type: str) -> Path:
        dialog = ConflictResolutionDialog(
            self,
            item_type,
            item_name,
            self._storage_relative_label(desired_path),
        )
        dialog.exec()

        if dialog.choice == "cancel":
            raise MoveCancelledError()

        if dialog.choice == "overwrite":
            if desired_path.is_dir():
                shutil.rmtree(desired_path)
            else:
                desired_path.unlink(missing_ok=True)
            return desired_path

        while True:
            new_name, confirmed = QInputDialog.getText(self, "Rename current item", "New name:", text=item_name)
            if not confirmed:
                raise MoveCancelledError()

            new_name = new_name.strip()
            if item_type == ITEM_TYPE_PROBLEM:
                new_name = self._display_title(new_name)

            if not new_name:
                QMessageBox.warning(self, "Invalid name", "Name cannot be empty.")
                continue

            new_path = desired_path.parent / new_name
            if new_path.exists():
                QMessageBox.warning(self, "Duplicate name", f"'{new_name}' already exists in the target location.")
                continue
            return new_path

    def _rename_problem_item(self, item: QTreeWidgetItem, item_data: dict) -> None:
        problem_data = item_data.get("problem_data")
        if not problem_data:
            return

        old_title = problem_data.get("title", "")
        new_title = self._display_title(item.text(0).strip())
        if new_title == old_title:
            return

        if not new_title:
            self._restore_tree_item_text(item, old_title)
            QMessageBox.warning(self, "Invalid name", "Task name cannot be empty.")
            return

        old_problem_dir = Path(item_data["path"])
        new_problem_dir = old_problem_dir.parent / new_title
        if new_problem_dir.exists():
            self._restore_tree_item_text(item, old_title)
            QMessageBox.warning(self, "Duplicate name", f"A task named '{new_title}' already exists.")
            return

        old_problem_dir.rename(new_problem_dir)
        image_file_name = Path(problem_data["image_path"]).name
        problem_data["title"] = new_title
        problem_data["image_path"] = str(new_problem_dir / image_file_name)
        self._write_problem_data(new_problem_dir, problem_data)
        self._restore_tree_item_text(item, new_title)
        item_data["path"] = str(new_problem_dir)
        item_data["problem_data"] = problem_data
        item.setData(0, USER_ROLE, item_data)

        if self.selected_problem_dir == old_problem_dir:
            self.selected_problem_dir = new_problem_dir
            self.selected_image_path = problem_data["image_path"]
            self.image_path_label.setText(f"Image: {self._storage_relative_label(self.selected_image_path)}")

        self.status_label.setText("Status: math problem renamed")

    def _sync_tree_to_storage(self, parent_item: QTreeWidgetItem, parent_dir: Path) -> None:
        for index in range(parent_item.childCount()):
            item = parent_item.child(index)
            item_data = item.data(0, USER_ROLE) or {}
            item_type = item_data.get("type")
            current_path = Path(item_data.get("path", parent_dir))

            if item_type == ITEM_TYPE_FOLDER:
                folder_name = item.text(0).strip()
                if not folder_name:
                    raise RuntimeError("Folder name cannot be empty.")

                desired_path = parent_dir / folder_name
                if not current_path.exists() and desired_path.exists():
                    current_path = desired_path
                if current_path != desired_path:
                    if desired_path.exists():
                        desired_path = self._resolve_move_conflict(folder_name, desired_path, ITEM_TYPE_FOLDER)
                    old_selected_problem_dir = self.selected_problem_dir
                    old_selected_image_path = self.selected_image_path
                    current_path.rename(desired_path)
                    self._rewrite_problem_paths_in_tree(desired_path)
                    self._update_selected_paths_after_move(
                        current_path,
                        desired_path,
                        old_selected_problem_dir,
                        old_selected_image_path,
                    )
                    current_path = desired_path

                item_data["path"] = str(current_path)
                item.setData(0, USER_ROLE, item_data)
                self._sync_tree_to_storage(item, current_path)

            elif item_type == ITEM_TYPE_PROBLEM:
                problem_data = item_data.get("problem_data", {})
                problem_title = self._display_title(item.text(0).strip())
                if not problem_title:
                    raise RuntimeError("Task name cannot be empty.")

                desired_path = parent_dir / problem_title
                old_problem_dir = current_path
                if not current_path.exists() and desired_path.exists():
                    current_path = desired_path
                    old_problem_dir = current_path
                if current_path != desired_path:
                    if desired_path.exists():
                        desired_path = self._resolve_move_conflict(problem_title, desired_path, ITEM_TYPE_PROBLEM)
                    current_path.rename(desired_path)
                    current_path = desired_path

                image_file_name = Path(problem_data.get("image_path", "")).name
                if not image_file_name:
                    raise RuntimeError(f"Task '{problem_title}' is missing the stored image path.")

                problem_data["title"] = problem_title
                problem_data["image_path"] = str(current_path / image_file_name)
                self._write_problem_data(current_path, problem_data)

                item_data["path"] = str(current_path)
                item_data["problem_data"] = problem_data
                item.setData(0, USER_ROLE, item_data)

                if self.selected_problem_dir == old_problem_dir:
                    self.selected_problem_dir = current_path
                    self.selected_image_path = problem_data["image_path"]
                    self.image_path_label.setText(f"Image: {self._storage_relative_label(self.selected_image_path)}")

    def _rewrite_problem_paths_in_tree(self, base_dir: Path) -> None:
        for problem_dir in base_dir.rglob("*"):
            if not problem_dir.is_dir():
                continue
            data_path = self._problem_data_path(problem_dir)
            if not data_path.exists():
                continue

            problem_data = self._read_problem_data(problem_dir)
            image_file_name = Path(problem_data.get("image_path", "")).name
            if not image_file_name:
                image_file_name = Path(self._find_problem_image_path(problem_dir)).name
            if image_file_name:
                problem_data["image_path"] = str(problem_dir / image_file_name)
            self._write_problem_data(problem_dir, problem_data)

    def _update_selected_paths_after_move(
        self,
        old_parent_dir: Path,
        new_parent_dir: Path,
        old_selected_problem_dir: Path | None,
        old_selected_image_path: str | None,
    ) -> None:
        if old_selected_problem_dir and (old_selected_problem_dir == old_parent_dir or old_parent_dir in old_selected_problem_dir.parents):
            relative_problem_dir = old_selected_problem_dir.relative_to(old_parent_dir)
            self.selected_problem_dir = new_parent_dir / relative_problem_dir
            if old_selected_image_path:
                image_file_name = Path(old_selected_image_path).name
                self.selected_image_path = str(self.selected_problem_dir / image_file_name)
                self.image_path_label.setText(f"Image: {self._storage_relative_label(self.selected_image_path)}")

    def _restore_tree_item_text(self, item: QTreeWidgetItem, text: str) -> None:
        self.is_updating_problem_tree = True
        item.setText(0, text)
        self.is_updating_problem_tree = False


def main() -> None:
    app = QApplication(sys.argv)
    window = MathOcrApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
