from io import BytesIO
import os

from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError


def _read_bounded(uploaded_file, maximum_size):
	if not uploaded_file or not uploaded_file.filename:
		raise ValueError("Choose a file to upload.")

	stream = uploaded_file.stream
	stream.seek(0, os.SEEK_END)
	size = stream.tell()
	stream.seek(0)
	if size <= 0 or size > maximum_size:
		raise ValueError("The uploaded file is empty or exceeds the allowed size.")
	contents = stream.read(maximum_size + 1)
	stream.seek(0)
	if len(contents) != size:
		raise ValueError("The uploaded file could not be read safely.")
	return contents


def save_sanitized_public_image(uploaded_file, destination, expected_format, maximum_size):
	contents = _read_bounded(uploaded_file, maximum_size)
	try:
		with Image.open(BytesIO(contents)) as source:
			if source.format != expected_format:
				raise ValueError("The image content does not match its file extension.")
			if source.width * source.height > Image.MAX_IMAGE_PIXELS:
				raise ValueError("The image dimensions exceed the allowed limit.")
			source.verify()

		with Image.open(BytesIO(contents)) as source:
			source.load()
			if expected_format == "GIF" and getattr(source, "n_frames", 1) > 1:
				frames = [ImageOps.exif_transpose(frame.copy()) for frame in ImageSequence.Iterator(source)]
				durations = [frame.info.get("duration", 100) for frame in ImageSequence.Iterator(source)]
				frames[0].save(
					destination,
					format="GIF",
					save_all=True,
					append_images=frames[1:],
					loop=source.info.get("loop", 0),
					duration=durations,
					optimize=True,
				)
				return

			image = ImageOps.exif_transpose(source).copy()
			if expected_format == "JPEG" and image.mode not in {"RGB", "L"}:
				image = image.convert("RGB")
			save_options = {"quality": 92, "optimize": True} if expected_format == "JPEG" else {}
			image.save(destination, format=expected_format, **save_options)
	except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
		raise ValueError("The uploaded file is not a valid supported image.") from error


def save_video_upload(uploaded_file, destination, extension, maximum_size):
	"""Allow only recognized MP4-family or WebM container signatures."""
	contents = _read_bounded(uploaded_file, maximum_size)
	if extension == "webm":
		valid_content = contents.startswith(b"\x1a\x45\xdf\xa3")
	else:
		valid_content = len(contents) >= 12 and contents[4:8] == b"ftyp"
	if not valid_content:
		raise ValueError("The video content does not match its file extension.")
	with open(destination, "wb") as output:
		output.write(contents)
