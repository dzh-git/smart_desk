"""Camera abstraction: selects between the OpenCV USB webcam driver and the
industrial MV (MindVision) SDK camera driver.  The factory is controlled by
``GestureConfig.camera_driver``.

Two backends are available:

- ``opencv``: uses ``cv2.VideoCapture`` with the legacy direct-capture logic
  previously in ``gesture_controller.py``.
- ``industrial``: uses Hikrobot/MindVision style MV_CC SDK.

A wrapper unifies both to a ``read() -> (ok, frame)`` / ``release()`` interface.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from typing import Any, Optional, Tuple

from .gesture_config import GestureConfig

logger = logging.getLogger("hands.camera")


class _OpenCvCamera:
    """cv2.VideoCapture wrapper with the legacy tuning parameters."""

    def __init__(self, config: GestureConfig) -> None:
        self.config = config
        self._cap: Optional[Any] = None

    def open(self) -> "_OpenCvCamera":
        import cv2

        cap = cv2.VideoCapture(self.config.camera_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            raise RuntimeError(
                f"camera {self.config.camera_index} could not be opened"
            )

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.camera_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.camera_height)
        cap.set(cv2.CAP_PROP_FPS, self.config.camera_fps)
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, self.config.camera_auto_exposure)
        cap.set(cv2.CAP_PROP_EXPOSURE, self.config.camera_exposure)
        cap.set(cv2.CAP_PROP_BRIGHTNESS, self.config.camera_brightness)
        cap.set(cv2.CAP_PROP_GAIN, self.config.camera_gain)

        time.sleep(1)

        actual_width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        actual_height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        actual_fps = cap.get(cv2.CAP_PROP_FPS)
        actual_auto = cap.get(cv2.CAP_PROP_AUTO_EXPOSURE)
        actual_exp = cap.get(cv2.CAP_PROP_EXPOSURE)
        actual_brightness = cap.get(cv2.CAP_PROP_BRIGHTNESS)
        actual_gain = cap.get(cv2.CAP_PROP_GAIN)

        logger.info(
            "[opencv] camera opened: requested %dx%d@%dfps | "
            "auto_exposure=%s exposure=%s brightness=%s gain=%s | "
            "actual %dx%d@%dfps auto=%s exp=%s brightness=%s gain=%s",
            self.config.camera_width,
            self.config.camera_height,
            self.config.camera_fps,
            self.config.camera_auto_exposure,
            self.config.camera_exposure,
            self.config.camera_brightness,
            self.config.camera_gain,
            actual_width,
            actual_height,
            actual_fps,
            actual_auto,
            actual_exp,
            actual_brightness,
            actual_gain,
        )
        self._cap = cap
        return self

    def read(self) -> Tuple[bool, Any]:
        if self._cap is None:
            return False, None
        return self._cap.read()

    def release(self) -> None:
        if self._cap is not None:
            import cv2
            cv2.VideoCapture.release(self._cap)
            self._cap = None


class _IndustrialCamera:
    """Industrial MV camera wrapper using the vendor SDK (Hikrobot/MV style).

    Built from the SDK patterns seen in ``camera_cap.py`` and the official
    Windows SDK Python guide.  It enumerates devices, opens the camera selected
    by ``config.industrial_camera_index``, sets width/height/pixel format and
    starts grabbing, returning BGR frames compatible with the rest of the
    pipeline.
    """

    def __init__(self, config: GestureConfig) -> None:
        self.config = config
        self._cam: Optional[Any] = None
        self._sdk: Optional[Any] = None
        self._opened: bool = False
        self._grabbing: bool = False
        self._frame_buffer: Optional[Any] = None
        self._buffer_size: int = 0

    def _import_sdk(self) -> Any:
        """Import the SDK module configured by the user.

        On Windows, if the module is not already on ``sys.path``, look for it
        under the Hikrobot MVS installation directory indicated by the
        ``MVCAM_COMMON_RUNENV`` environment variable (same convention as the
        reference ``camera_cap.py`` script).
        """
        module_name = self.config.industrial_sdk_module or "MvCameraControl"
        try:
            return __import__(module_name)
        except ImportError:
            pass

        # Fallback: append the standard SDK import path on Windows.
        env_dir = os.getenv("MVCAM_COMMON_RUNENV")
        if env_dir:
            sdk_path = os.path.join(env_dir, "Samples", "Python", "MvImport")
            if sdk_path not in sys.path:
                sys.path.append(sdk_path)

        try:
            return __import__(module_name)
        except ImportError as exc:
            raise RuntimeError(
                f"industrial camera driver requires SDK module '{module_name}'. "
                "Install Hikrobot MVS and set the MVCAM_COMMON_RUNENV environment "
                "variable, then restart."
            ) from exc

    def _enum_devices(self, sdk: Any) -> Any:
        """Enumerate available cameras and return the device list object."""
        # SDK interface: get transport layer type enum and device list structure.
        tlayerType = sdk.MV_GIGE_DEVICE | sdk.MV_USB_DEVICE
        device_list = sdk.MV_CC_DEVICE_INFO_LIST()
        ret = sdk.MvCamera.MV_CC_EnumDevices(tlayerType, device_list)
        if ret != 0:
            raise RuntimeError(f"MV_CC_EnumDevices failed: ret=0x{ret:x}")
        if device_list.nDeviceNum == 0:
            raise RuntimeError("no industrial camera found")
        return device_list

    def _select_device(self, sdk: Any, device_list: Any) -> Any:
        """Return the device info for the configured camera index."""
        import ctypes

        index = self.config.industrial_camera_index
        if index < 0 or index >= device_list.nDeviceNum:
            raise RuntimeError(
                f"industrial camera index {index} out of range "
                f"(0-{device_list.nDeviceNum - 1})"
            )
        return ctypes.cast(
            device_list.pDeviceInfo[index],
            ctypes.POINTER(sdk.MV_CC_DEVICE_INFO),
        ).contents

    def _set_camera_parameter(self, sdk: Any, cam: Any, key: str, value: Any) -> None:
        """Best-effort set of a camera parameter, logging a warning on failure."""
        try:
            if isinstance(value, int):
                ret = cam.MV_CC_SetIntValue(key, value)
            elif isinstance(value, float):
                ret = cam.MV_CC_SetFloatValue(key, value)
            elif isinstance(value, bool):
                ret = cam.MV_CC_SetBoolValue(key, value)
            elif isinstance(value, str):
                ret = cam.MV_CC_SetStringValue(key, value)
            else:
                ret = -1
            if ret != 0:
                logger.warning(
                    "[industrial] set parameter %s=%s failed: ret=0x%x",
                    key, value, ret
                )
        except Exception:
            logger.exception("[industrial] set parameter %s=%s failed", key, value)

    def _set_enum_param_by_string(self, sdk: Any, cam: Any, key: str, value: str) -> None:
        """Best-effort set of an enum node by string value."""
        try:
            ret = cam.MV_CC_SetEnumValueByString(key, value)
            if ret != 0:
                logger.warning(
                    "[industrial] set enum %s=%s failed: ret=0x%x", key, value, ret
                )
        except Exception:
            logger.exception("[industrial] set enum %s=%s failed", key, value)

    def open(self) -> "_IndustrialCamera":
        sdk = self._import_sdk()
        self._sdk = sdk

        # Initialize the SDK runtime (once per process).
        ret = sdk.MvCamera.MV_CC_Initialize()
        if ret != 0:
            raise RuntimeError(f"MV_CC_Initialize failed: ret=0x{ret:x}")

        device_list = self._enum_devices(sdk)
        device_info = self._select_device(sdk, device_list)

        cam = sdk.MvCamera()
        ret = cam.MV_CC_CreateHandle(device_info)
        if ret != 0:
            raise RuntimeError(f"MV_CC_CreateHandle failed: ret=0x{ret:x}")

        ret = cam.MV_CC_OpenDevice(sdk.MV_ACCESS_Exclusive, 0)
        if ret != 0:
            raise RuntimeError(f"MV_CC_OpenDevice failed: ret=0x{ret:x}")

        self._cam = cam
        self._opened = True

        # Apply tunable parameters from config.
        # Enum nodes must be set by string.
        self._set_enum_param_by_string(sdk, cam, "TriggerMode", "Off")
        self._set_enum_param_by_string(
            sdk, cam, "ExposureAuto",
            "Continuous" if self.config.industrial_exposure_auto else "Off"
        )
        self._set_enum_param_by_string(
            sdk, cam, "GainAuto",
            "Continuous" if self.config.industrial_gain_auto else "Off"
        )
        self._set_enum_param_by_string(
            sdk, cam, "BalanceWhiteAuto",
            "Continuous" if self.config.industrial_balance_white_auto else "Off"
        )
        if self.config.industrial_pixel_format:
            self._set_enum_param_by_string(sdk, cam, "PixelFormat", self.config.industrial_pixel_format)

        # Set resolution to the camera's maximum supported width/height.
        stWidthInfo = sdk.MVCC_INTVALUE_EX()
        stHeightInfo = sdk.MVCC_INTVALUE_EX()
        import ctypes
        ctypes.memset(ctypes.byref(stWidthInfo), 0, ctypes.sizeof(stWidthInfo))
        ctypes.memset(ctypes.byref(stHeightInfo), 0, ctypes.sizeof(stHeightInfo))
        ret = cam.MV_CC_GetIntValueEx("Width", stWidthInfo)
        if ret != 0:
            raise RuntimeError(f"MV_CC_GetIntValueEx Width failed: ret=0x{ret:x}")
        ret = cam.MV_CC_SetIntValueEx("Width", stWidthInfo.nMax)
        if ret != 0:
            raise RuntimeError(f"MV_CC_SetIntValueEx Width failed: ret=0x{ret:x}")
        ret = cam.MV_CC_GetIntValueEx("Height", stHeightInfo)
        if ret != 0:
            raise RuntimeError(f"MV_CC_GetIntValueEx Height failed: ret=0x{ret:x}")
        ret = cam.MV_CC_SetIntValueEx("Height", stHeightInfo.nMax)
        if ret != 0:
            raise RuntimeError(f"MV_CC_SetIntValueEx Height failed: ret=0x{ret:x}")

        # Int/float nodes use the generic helper.
        self._set_camera_parameter(sdk, cam, "AcquisitionFrameRate", self.config.industrial_fps)
        self._set_camera_parameter(sdk, cam, "ExposureTime", self.config.industrial_exposure_time)
        if self.config.industrial_gain >= 0:
            self._set_camera_parameter(sdk, cam, "Gain", self.config.industrial_gain)

        # SDK internal buffer count (some SDK versions may not expose this).
        try:
            cam.MV_CC_SetImageNodeNum(self.config.industrial_image_node_num)
        except Exception:
            logger.warning(
                "[industrial] MV_CC_SetImageNodeNum not supported by this SDK",
                exc_info=True,
            )

        # Payload size determines the max buffer size needed for GetImageBuffer.
        stParam = sdk.MVCC_INTVALUE()
        # memset via ctypes import below (kept local to avoid import at module load).
        import ctypes
        ctypes.memset(ctypes.byref(stParam), 0, ctypes.sizeof(stParam))
        ret = cam.MV_CC_GetIntValue("PayloadSize", stParam)
        if ret != 0:
            raise RuntimeError(f"MV_CC_GetIntValue PayloadSize failed: ret=0x{ret:x}")
        # Bayer formats need up to 3 bytes per pixel after conversion to RGB/BGR,
        # and 10/12-bit formats can need 2 bytes per raw pixel.  Allocate enough
        # for the worst case so ConvertPixelType never reports MV_E_BUFOVER.
        # Use the actual maximum resolution just configured (stWidthInfo.nMax / nMax).
        min_rgb_size = stWidthInfo.nMax * stHeightInfo.nMax * 3 * 2
        self._buffer_size = max(stParam.nCurValue, min_rgb_size)
        self._frame_buffer = (ctypes.c_ubyte * self._buffer_size)()

        ret = cam.MV_CC_StartGrabbing()
        if ret != 0:
            raise RuntimeError(f"MV_CC_StartGrabbing failed: ret=0x{ret:x}")
        self._grabbing = True

        # Log actual parameters where possible.
        actual_w = self._get_int_param("Width")
        actual_h = self._get_int_param("Height")
        actual_fps = self._get_float_param("AcquisitionFrameRate")
        actual_exp = self._get_float_param("ExposureTime")
        actual_gain = self._get_float_param("Gain")
        logger.info(
            "[industrial] camera opened: requested %dx%d@%s fps | "
            "exposure_auto=%s exposure_time=%s gain=%s gain_auto=%s | "
            "actual %sx%s fps=%s exp=%s gain=%s",
            self.config.industrial_width,
            self.config.industrial_height,
            self.config.industrial_fps,
            self.config.industrial_exposure_auto,
            self.config.industrial_exposure_time,
            self.config.industrial_gain,
            self.config.industrial_gain_auto,
            actual_w,
            actual_h,
            actual_fps,
            actual_exp,
            actual_gain,
        )
        return self

    def _get_int_param(self, key: str) -> Optional[Any]:
        if self._cam is None or self._sdk is None:
            return None
        try:
            st = self._sdk.MVCC_INTVALUE()
            import ctypes
            ctypes.memset(ctypes.byref(st), 0, ctypes.sizeof(st))
            ret = self._cam.MV_CC_GetIntValue(key, st)
            if ret == 0:
                return st.nCurValue
        except Exception:
            logger.exception("[industrial] get int param %s failed", key)
        return None

    def _get_float_param(self, key: str) -> Optional[Any]:
        if self._cam is None or self._sdk is None:
            return None
        try:
            st = self._sdk.MVCC_FLOATVALUE()
            import ctypes
            ctypes.memset(ctypes.byref(st), 0, ctypes.sizeof(st))
            ret = self._cam.MV_CC_GetFloatValue(key, st)
            if ret == 0:
                return st.fCurValue
        except Exception:
            logger.exception("[industrial] get float param %s failed", key)
        return None

    def read(self) -> Tuple[bool, Any]:
        import ctypes
        import cv2
        import numpy as np

        if self._cam is None or not self._grabbing or self._frame_buffer is None:
            return False, None

        # Some cameras take a few frames to stabilize after StartGrabbing.
        # Retry a small number of times before giving up so a transient
        # timeout doesn't kill the whole controller loop.
        stOutFrame = self._sdk.MV_FRAME_OUT()
        retries = 3
        for attempt in range(retries):
            ctypes.memset(ctypes.byref(stOutFrame), 0, ctypes.sizeof(stOutFrame))
            ret = self._cam.MV_CC_GetImageBuffer(stOutFrame, self.config.industrial_get_timeout_ms)
            if ret == 0 and stOutFrame.pBufAddr is not None:
                break
            if attempt < retries - 1:
                logger.debug("[industrial] frame timeout, retrying (%d/%d)", attempt + 1, retries)
                time.sleep(0.05)
        else:
            logger.debug("[industrial] no frame after %d attempts (ret=0x%x)", retries, ret if ret is not None else -1)
            return False, None

        try:
            n_width = stOutFrame.stFrameInfo.nWidth
            n_height = stOutFrame.stFrameInfo.nHeight
            n_len = stOutFrame.stFrameInfo.nFrameLen
            pixel_type = stOutFrame.stFrameInfo.enPixelType

            sdk = self._sdk
            # Convert the frame to BGR8 for the rest of the pipeline.
            bayer_types = (
                sdk.PixelType_Gvsp_BayerGR8, sdk.PixelType_Gvsp_BayerRG8,
                sdk.PixelType_Gvsp_BayerGB8, sdk.PixelType_Gvsp_BayerBG8,
                sdk.PixelType_Gvsp_BayerGR10, sdk.PixelType_Gvsp_BayerRG10,
                sdk.PixelType_Gvsp_BayerGB10, sdk.PixelType_Gvsp_BayerBG10,
            )

            if pixel_type == sdk.PixelType_Gvsp_BGR8_Packed:
                ctypes.memmove(self._frame_buffer, stOutFrame.pBufAddr, n_len)
                img = np.array(self._frame_buffer, dtype=np.uint8)[:n_len].reshape((n_height, n_width, 3))
            elif pixel_type == sdk.PixelType_Gvsp_RGB8_Packed:
                ctypes.memmove(self._frame_buffer, stOutFrame.pBufAddr, n_len)
                rgb = np.array(self._frame_buffer, dtype=np.uint8)[:n_len].reshape((n_height, n_width, 3))
                img = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            elif pixel_type == sdk.PixelType_Gvsp_Mono8:
                ctypes.memmove(self._frame_buffer, stOutFrame.pBufAddr, n_len)
                mono = np.array(self._frame_buffer, dtype=np.uint8)[:n_len].reshape((n_height, n_width))
                img = cv2.cvtColor(mono, cv2.COLOR_GRAY2BGR)
            elif pixel_type in bayer_types:
                n_rgb_size = n_width * n_height * 3
                stConvert = sdk.MV_CC_PIXEL_CONVERT_PARAM_EX()
                ctypes.memset(ctypes.byref(stConvert), 0, ctypes.sizeof(stConvert))
                stConvert.nWidth = n_width
                stConvert.nHeight = n_height
                stConvert.pSrcData = stOutFrame.pBufAddr
                stConvert.nSrcDataLen = n_len
                stConvert.enSrcPixelType = pixel_type
                stConvert.enDstPixelType = sdk.PixelType_Gvsp_RGB8_Packed
                stConvert.pDstBuffer = self._frame_buffer
                stConvert.nDstBufferSize = self._buffer_size
                ret = self._cam.MV_CC_ConvertPixelTypeEx(stConvert)
                if ret != 0:
                    logger.warning("[industrial] Bayer convert failed: 0x%x", ret)
                    self._cam.MV_CC_FreeImageBuffer(stOutFrame)
                    return False, None
                dst_len = getattr(stConvert, "nDstLen", n_rgb_size)
                rgb = np.array(self._frame_buffer, dtype=np.uint8)[:dst_len].reshape((n_height, n_width, 3))
                img = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            else:
                # Generic fallback: convert to BGR8_Packed.
                stConvert = sdk.MV_CC_PIXEL_CONVERT_PARAM_EX()
                ctypes.memset(ctypes.byref(stConvert), 0, ctypes.sizeof(stConvert))
                stConvert.nWidth = n_width
                stConvert.nHeight = n_height
                stConvert.pSrcData = stOutFrame.pBufAddr
                stConvert.nSrcDataLen = n_len
                stConvert.enSrcPixelType = pixel_type
                stConvert.enDstPixelType = sdk.PixelType_Gvsp_BGR8_Packed
                stConvert.pDstBuffer = self._frame_buffer
                stConvert.nDstBufferSize = self._buffer_size
                ret = self._cam.MV_CC_ConvertPixelTypeEx(stConvert)
                if ret != 0:
                    logger.warning("[industrial] convert pixel type failed: 0x%x", ret)
                    self._cam.MV_CC_FreeImageBuffer(stOutFrame)
                    return False, None
                dst_len = getattr(stConvert, "nDstLen", n_width * n_height * 3)
                img = np.array(self._frame_buffer, dtype=np.uint8)[:dst_len].reshape((n_height, n_width, 3))
        finally:
            self._cam.MV_CC_FreeImageBuffer(stOutFrame)

        return True, img

    def release(self) -> None:
        sdk = self._sdk
        if self._cam is not None:
            try:
                if self._grabbing:
                    self._cam.MV_CC_StopGrabbing()
                    self._grabbing = False
            except Exception:
                logger.exception("[industrial] stop grabbing failed")
            try:
                if self._opened:
                    self._cam.MV_CC_CloseDevice()
                    self._opened = False
            except Exception:
                logger.exception("[industrial] close device failed")
            try:
                self._cam.MV_CC_DestroyHandle()
            except Exception:
                logger.exception("[industrial] destroy handle failed")
        if sdk is not None:
            try:
                sdk.MvCamera.MV_CC_Finalize()
            except Exception:
                logger.exception("[industrial] finalize failed")
        self._cam = None
        self._sdk = None
        self._frame_buffer = None


def create_camera(config: GestureConfig) -> Any:
    """Factory that creates the camera driver selected by ``config.camera_driver``."""
    driver = config.camera_driver.lower()
    if driver == "opencv":
        return _OpenCvCamera(config).open()
    elif driver == "industrial":
        return _IndustrialCamera(config).open()
    else:
        raise ValueError(f"unknown camera_driver: {config.camera_driver!r}")
