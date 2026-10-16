"""Editing and deleting saved phrases, categories and answers."""

import copy

from ..keyboard_layouts import ARABIC_SCRIPT
from ..speech.speech_library import CategoryRecord, PhraseRecord, clean_text, saved_entry_texts
from ..suggestions.composition import Composition
from .speech_editor import EditorContext, EditorKind, EntryError, page_for_text

ITEMS_PER_PAGE = 6


class SpeechLibraryActions:
    def _sync_saved_audio(self) -> None:
        self._speech.set_saved_texts(saved_entry_texts(self._library_store, self._library))

    def _start_editor(self) -> None:
        if not self._is_list_mode():
            return
        kind: EditorKind
        if self._view_mode == "phrases":
            kind = "phrase"
        elif self._view_mode == "answers":
            kind = "answer"
        else:
            kind = "category"
        self._editor = EditorContext(
            kind=kind,
            category_index=self._category_index,
            page=self._list_page,
            message=self._input.text(),
        )
        self._conversation = self._composition
        self._composition = Composition(self._suggestions.store, learn=False)
        self._input.clear()
        self._view_mode = "editor"
        self._deletion_mode = False
        self._symbols_mode = False
        self._show_group_level()
        self._view_title.setText(self._editor_title())
        self._update_view_controls()
        self._set_status("Unesite tekst pomoću grupa slova, zatim odaberite Sačuvaj.")

    def _save_editor(self) -> None:
        if self._editor is None:
            return
        text = clean_text(self._input.text()).upper()
        editor = self._editor
        try:
            candidate = editor.prepare_entry(self._library, text)
        except EntryError as error:
            self._set_status(str(error))
            return

        if not self._library_store.save(candidate):
            self._set_status("Čuvanje nije uspjelo. Novi unos nije sačuvan.")
            return

        self._library = candidate
        self._sync_saved_audio()
        if (
            editor.kind in ("phrase", "answer")
            and self._speech_settings.keyboard_script != ARABIC_SCRIPT
        ):
            self._suggestions.store.learn_text(text)
            self._suggestions.persist()
        self._composition = self._conversation
        self._input.setText(editor.message)
        self._view_mode = editor.list_mode
        self._category_index = editor.category_index
        self._editor = None
        self._list_page = self._page_for_saved_item(editor.kind, text)
        self._show_list_level()
        self._set_status("Sačuvano. Vaša poruka je vraćena.")

    def _cancel_editor(self) -> None:
        if self._editor is None:
            return
        editor = self._editor
        self._composition = self._conversation
        self._input.setText(editor.message)
        self._view_mode = editor.list_mode
        self._category_index = editor.category_index
        self._list_page = editor.page
        self._editor = None
        self._show_list_level()
        self._set_status("Dodavanje je otkazano. Vaša poruka je vraćena.")

    def _restore_message_if_editing(self) -> None:
        if self._editor is not None:
            self._composition = self._conversation
            self._input.setText(self._editor.message)

    def _page_for_saved_item(self, kind: str, text: str) -> int:
        if kind == "category":
            values = [category.name for category in self._library.categories]
        elif kind == "phrase":
            values = [phrase.text for phrase in self._library.phrases]
        else:
            category = self._active_category()
            values = category.answers if category is not None else []
        return page_for_text(values, text, ITEMS_PER_PAGE)

    def _toggle_deletion_mode(self) -> None:
        if not self._is_list_mode():
            return
        self._deletion_mode = not self._deletion_mode
        self._show_list_level()

    def _confirm_item_deletion(self, index: int) -> None:
        items = self._list_items()
        if index < 0 or index >= len(items):
            return
        item = items[index]
        if isinstance(item, CategoryRecord):
            name = item.name.upper()
            copy_text = f'Kategorija "{name}" i svi njeni odgovori bit će obrisani.'
        else:
            text = item.text if isinstance(item, PhraseRecord) else item
            text = text.upper()
            copy_text = f'"{text}" će biti obrisano iz liste.'
        view_mode = self._view_mode
        category_index = self._category_index
        self._open_confirmation(
            "Obrisati ovu stavku?",
            copy_text,
            "Obriši",
            lambda: self._delete_list_item(view_mode, category_index, index),
        )

    def _delete_list_item(
        self,
        view_mode: str,
        category_index: int | None,
        index: int,
    ) -> None:
        candidate = copy.deepcopy(self._library)
        items = _deletion_items(candidate, view_mode, category_index)
        if items is None:
            return
        if not 0 <= index < len(items):
            return
        del items[index]
        if not self._library_store.save(candidate):
            self._set_status("Brisanje nije sačuvano. Stavka nije obrisana.")
            return
        self._library = candidate
        self._sync_saved_audio()
        self._clamp_list_page()
        self._show_list_level()
        self._set_status("Stavka je obrisana.")


def _deletion_items(candidate, view_mode, category_index):
    if view_mode == "categories":
        return candidate.categories
    elif view_mode == "phrases":
        return candidate.phrases
    elif category_index is not None and 0 <= category_index < len(candidate.categories):
        return candidate.categories[category_index].answers
    else:
        return None
