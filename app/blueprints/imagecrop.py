########################################################################
### IMAGE CROP -- BROWSER-ONLY SELECT-AND-CROP, NO PDF INVOLVED
###
### Entirely client-side: load an image file, draw a selection on a
### canvas, crop to a second canvas, open the result in a new window.
### Nothing is uploaded or touches the server past this one page load.
########################################################################
from flask import Blueprint, render_template

bp = Blueprint("imagecrop", __name__)


@bp.route("/image-crop")
def image_crop():
    return render_template("image_crop.html")
