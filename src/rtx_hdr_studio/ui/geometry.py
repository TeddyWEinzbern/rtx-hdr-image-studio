"""Shared image placement in physical pixels for Qt and native HDR previews."""


def image_placement(image_width, image_height, width, height, mode="fit", margin=0):
    """Return centered x, y, width, height; actual size falls back to fit if oversized."""
    available_width = max(1, width - margin * 2)
    available_height = max(1, height - margin * 2)
    if mode == "stretch":
        iw, ih = available_width, available_height
    elif mode == "actual" and image_width <= available_width and image_height <= available_height:
        iw, ih = image_width, image_height
    else:
        choose_scale = max if mode == "fill" else min
        scale = choose_scale(available_width / image_width, available_height / image_height)
        iw = max(1, round(image_width * scale))
        ih = max(1, round(image_height * scale))
    return (width - iw) // 2, (height - ih) // 2, iw, ih
