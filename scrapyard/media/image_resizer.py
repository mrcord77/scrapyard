"""
image_resizer — The image_resizer module provides core functionality for resizing images to specified dimensions, forming the foundation for more complex image manipulation tasks.

### PART-META-JSON
{
  "name": "image_resizer",
  "layer": "media",
  "purpose": "The image_resizer module provides core functionality for resizing images to specified dimensions, forming the foundation for more complex image manipulation tasks.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "Pillow"
  ],
  "inputs": "Public API: resize_image(image, width, height); ImageResizer(...).",
  "outputs": "Returns: resize_image -> Image.Image.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.media.image_resizer`.",
  "example": "from scrapyard.media.image_resizer import *",
  "import_path": "scrapyard.media.image_resizer"
}
### END-PART-META
"""

from PIL import Image

def resize_image(image: Image.Image, width: int, height: int) -> Image.Image:
    """
    Resize an image to the specified dimensions using Pillow.
    
    :param image: The input image to be resized.
    :param width: The desired width of the resized image.
    :param height: The desired height of the resized image.
    :return: A new Image object with the specified dimensions.
    """
    if not isinstance(image, Image.Image):
        raise ValueError("Input must be an instance of PIL.Image.Image")
    
    return image.resize((width, height), resample=Image.LANCZOS)

class ImageResizer:
    def __init__(self, image: Image.Image):
        """
        Initialize the ImageResizer with a given image.
        
        :param image: The input image to be resized.
        """
        if not isinstance(image, Image.Image):
            raise ValueError("Input must be an instance of PIL.Image.Image")
        
        self.image = image

    def resize(self, width: int, height: int) -> Image.Image:
        """
        Resize the stored image to the specified dimensions.
        
        :param width: The desired width of the resized image.
        :param height: The desired height of the resized image.
        :return: A new Image object with the specified dimensions.
        """
        return self.image.resize((width, height), resample=Image.LANCZOS)

# Self-test suite
def _selftest():
    from PIL import Image as PILImage
    
    # Create a sample image (using a test pattern)
    test_image = PILImage.new('RGB', size=(200, 300), color='red')
    
    # Test resize_image function
    resized_image = resize_image(test_image, 100, 150)
    assert isinstance(resized_image, PILImage.Image), "resize_image should return a PIL Image object"
    assert resized_image.size == (100, 150), f"Expected size (100, 150), got {resized_image.size}"
    
    # Test ImageResizer class
    resizer = ImageResizer(test_image)
    resized_image_class = resizer.resize(100, 150)
    assert isinstance(resized_image_class, PILImage.Image), "resize should return a PIL Image object"
    assert resized_image_class.size == (100, 150), f"Expected size (100, 150), got {resized_image_class.size}"
    
    # Test invalid input
    try:
        resize_image("not_an_image", 100, 150)
        assert False, "resize_image should raise ValueError for non-Image objects"
    except ValueError:
        pass
    
    print("All tests passed!")

if __name__ == "__main__":
    _selftest()
