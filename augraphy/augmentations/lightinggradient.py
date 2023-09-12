import random

import cv2
import numpy as np
from numba import config
from numba import jit

from augraphy.base.augmentation import Augmentation


class LightingGradient(Augmentation):
    """Generates a decayed light mask generated by light strip given its
    position and direction, and applies it to the image as a lighting or
    brightness gradient.

    :param position: Tuple of ints (x, y) defining the center of light
        strip position, which is the reference point during rotation.
    :type position: tuple, optional
    :param direction: Integer from 0 to 360 to indicate the rotation
        degree of light strip.
    :type direction: int, optional
    :param max_brightness: Integer that max brightness in the mask.
    :type max_brightness: int, optional
    :param min_brightness: Integer that min brightness in the mask
    :type min_brightness: int, optional
    :param mode: The way that brightness decay from max to min:
        linear or gaussian
    :type mode: string, optional
    :param linear_decay_rate: Only valid in linear_static mode.
        Suggested value is within [0.2, 2].
    :type linear_decay_rate: float, optional
    :param transparency: Transparency of input image.
    :type transparency: float, optional
    :param numba_jit: The flag to enable numba jit to speed up the processing in the augmentation.
    :type numba_jit: int, optional
    :param p: The probability this Augmentation will be applied.
    :type p: float, optional
    """

    def __init__(
        self,
        light_position=None,
        direction=None,
        max_brightness=255,
        min_brightness=0,
        mode="gaussian",
        linear_decay_rate=None,
        transparency=None,
        numba_jit=1,
        p=1,
    ):
        """Constructor method"""
        super().__init__(p=p, numba_jit=numba_jit)
        self.light_position = light_position
        self.direction = direction
        self.max_brightness = max_brightness
        self.min_brightness = min_brightness
        self.mode = mode
        self.linear_decay_rate = linear_decay_rate
        self.transparency = transparency
        self.numba_jit = numba_jit
        config.DISABLE_JIT = bool(1 - numba_jit)

    # Constructs a string representation of this Augmentation.
    def __repr__(self):
        return f"LightingGradient(light_position={self.light_position}, direction={self.direction}, max_brightness={self.max_brightness}, min_brightness={self.min_brightness}, mode='{self.mode}', linear_decay_rate={self.linear_decay_rate}, transparency={self.transparency}, numba_jit={self.numba_jit}, p={self.p})"

    def generate_parallel_light_mask(
        self,
        mask_size,
        position=None,
        direction=None,
        max_brightness=255,
        min_brightness=0,
        mode="gaussian",
        linear_decay_rate=None,
    ):
        """Generates mask of parallel light.

        :param mask_size: Tuple of ints (w, h) defining generated mask size
        :type mask_size: tuple
        :param position: Tuple of ints (x, y) defining the center of light strip position, which is the reference point during rotation.
        :type position: tuple
        :param direction: Integer from 0 to 360 to indicate the rotation egree of light strip.
        :type direction: int
        :param max_brightness: Integer that max brightness in the mask.
        :type max_brightness: int
        :param min_brightness: Integer that min brightness in the mask
        :type min_brightness: int
        :param mode: The way that brightness decay from max to min: linear or gaussian.
        :type mode: string
        :param linear_decay_rate: Only valid in linear_static mode. Suggested value is within [0.2, 2].
        :type linear_decay_rate: float
        """

        if position is None:
            pos_x = random.randint(0, mask_size[0])
            pos_y = random.randint(0, mask_size[1])
        else:
            pos_x = position[0]
            pos_y = position[1]
        if direction is None:
            direction = random.randint(0, 360)
        if linear_decay_rate is None:
            if mode == "linear_static":
                linear_decay_rate = random.uniform(0.2, 2)
        # change invalid mode into gaussian
        if mode not in ["linear_dynamic", "linear_static", "gaussian"]:
            mode = "gaussian"
        if mode == "linear_dynamic":
            linear_decay_rate = (max_brightness - min_brightness) / max(mask_size)

        padding = int(max(mask_size) * np.sqrt(2))
        # add padding to satisfy cropping after rotating
        canvas_x = padding * 2 + mask_size[0]
        canvas_y = padding * 2 + mask_size[1]
        mask = np.zeros(shape=(canvas_y, canvas_x), dtype=np.float32)
        # initial mask's up left corner and bottom right corner coordinate
        init_mask_ul = (int(padding), int(padding))
        init_mask_br = (int(padding + mask_size[0]), int(padding + mask_size[1]))
        init_light_pos = (padding + pos_x, padding + pos_y)

        # fill in mask row by row with value decayed from center
        if mode == "gaussian":
            self.apply_decay_value_norm(mask, canvas_y, max_brightness, min_brightness, init_light_pos[1], mask_size[1])
        else:
            self.apply_decay_value_linear(mask, canvas_y, max_brightness, init_light_pos[1], linear_decay_rate)

        # rotate mask
        rotate_M = cv2.getRotationMatrix2D(init_light_pos, direction, 1)
        mask = cv2.warpAffine(mask, rotate_M, (canvas_x, canvas_y))
        # crop
        mask = mask[
            init_mask_ul[1] : init_mask_br[1],
            init_mask_ul[0] : init_mask_br[0],
        ]
        mask = np.asarray(mask, dtype=np.uint8)
        # add median blur
        mask = cv2.medianBlur(mask, 9)
        mask = 255 - mask

        return mask

    # thanks to the formula in this discussion to replace the usage of norm.pdf:
    # https://stackoverflow.com/questions/8669235/alternative-for-scipy-stats-norm-pdf
    @staticmethod
    @jit(nopython=True, cache=True)
    def apply_decay_value_norm(mask, canvas_y, max_value, min_value, center, grange):
        """Decay from max to min value following Gaussian distribution

        :param mask: Output image
        :type mask: numpy.array
        :param canvas_y: Lighting image canvas max size.
        :type canvas_y: int
        :param max_value: Max of decayed value.
        :type max_value: int
        :param min_value: Min of decayed value.
        :type min_value: int
        :param center: Center of decayed value
        :type center: int
        :param grange: Range of decay.
        :type grange: int
        """

        for x in range(canvas_y):

            radius = grange / 3
            center_prob = 1 / (np.sqrt(2 * np.pi) * abs(radius))

            u = (x - center) / abs(radius)
            x_prob = (1 / (np.sqrt(2 * np.pi) * abs(radius))) * np.exp(-u * u / 2)

            x_value = (x_prob / center_prob) * (max_value - min_value) + min_value
            mask[x] = x_value

    @staticmethod
    @jit(nopython=True, cache=True)
    def apply_decay_value_linear(mask, canvas_y, max_value, padding_center, decay_rate):
        """Decay from max to min value with static linear decay rate.

        :param mask: Output image
        :type mask: numpy.array
        :param canvas_y: Lighting image canvas max size.
        :type canvas_y: int
        :param max_value: Max of decayed value.
        :type max_value: int
        :param padding_center: Center padding position.
        :type padding_center: int
        :param decay_rate: Rate of linear decay.
        :type decay_rate: float
        """

        for x in range(canvas_y):
            x_value = max_value - abs(padding_center - x) * decay_rate
            if x_value < 0:
                x_value = 1
            mask[x] = x_value

        return x_value

    # Applies the Augmentation to input data.
    def __call__(self, image, layer=None, mask=None, keypoints=None, bounding_boxes=None, force=False):
        if force or self.should_run():
            frame = image.copy()

            has_alpha = 0
            if len(frame.shape) > 2 and frame.shape[2] == 4:
                has_alpha = 1
                frame, image_alpha = frame[:, :, :3], frame[:, :, 3]

            if self.transparency is None:
                transparency = random.uniform(0.5, 0.85)
            else:
                transparency = self.transparency

            height, width = frame.shape[:2]
            if len(frame.shape) > 2:
                hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            else:
                bgr = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)

            lighting_mask = self.generate_parallel_light_mask(
                mask_size=(width, height),
                position=self.light_position,
                direction=self.direction,
                max_brightness=self.max_brightness,
                min_brightness=self.min_brightness,
                mode=self.mode,
                linear_decay_rate=self.linear_decay_rate,
            )
            hsv[:, :, 2] = hsv[:, :, 2] * transparency + lighting_mask * (1 - transparency)
            frame = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
            frame[frame > 255] = 255
            frame = np.asarray(frame, dtype=np.uint8)

            if has_alpha:
                frame = np.dstack((frame, image_alpha))

            # check for additional output of mask, keypoints and bounding boxes
            outputs_extra = []
            if mask is not None or keypoints is not None or bounding_boxes is not None:
                outputs_extra = [mask, keypoints, bounding_boxes]

            # returns additional mask, keypoints and bounding boxes if there is additional input
            if outputs_extra:
                # returns in the format of [image, mask, keypoints, bounding_boxes]
                return [frame] + outputs_extra
            else:
                return frame
