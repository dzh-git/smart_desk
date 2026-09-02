from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


AGENT_DIR = (
    Path(__file__).resolve().parent.parent / "host_services" / "display_agent"
)
sys.path.insert(0, str(AGENT_DIR))


def test_start_slideshow_falls_back_to_dispatch_when_rot_wrapper_is_incomplete(
) -> None:
    import powerpoint_control

    class IncompleteApplication:
        @property
        def Presentations(self):
            raise AttributeError("PowerPoint.Application.Presentations")

    incomplete = IncompleteApplication()
    settings = MagicMock()
    presentation = MagicMock(SlideShowSettings=settings)
    usable = MagicMock()
    usable.Presentations.Count = 1
    usable.Presentations.Item.return_value = presentation
    usable.SlideShowWindows.Count = 0
    client = MagicMock()
    client.GetActiveObject.return_value = incomplete
    client.Dispatch.return_value = usable
    fake_pythoncom = SimpleNamespace(
        CoInitialize=MagicMock(),
        CoUninitialize=MagicMock(),
    )
    fake_win32com = SimpleNamespace(client=client)

    with patch.object(
        powerpoint_control,
        "is_com_available",
        return_value=True,
    ), patch.dict(
        sys.modules,
        {
            "pythoncom": fake_pythoncom,
            "win32com": fake_win32com,
            "win32com.client": client,
        },
    ):
        result = powerpoint_control.start_slideshow_on_display(0)

    assert result == {"ok": True}
    client.Dispatch.assert_called_once_with("PowerPoint.Application")
    settings.Run.assert_called_once_with()
