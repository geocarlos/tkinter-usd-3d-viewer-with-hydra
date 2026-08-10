from OpenGL import GL
from PIL import Image


def to_gl_matrix(matrix4d):
    """Column-major flattening of a Gf.Matrix4d (row-vector convention) into
    the layout glLoadMatrixd expects for column-vector GL math -- i.e. the
    transpose of Gf's row-major storage, transposed by hand here rather than
    via glLoadTransposeMatrixd, which some drivers (e.g. Intel/Windows) accept
    without error but silently fail to apply."""
    rows = [list(row) for row in matrix4d]
    return [rows[col][row] for col in range(4) for row in range(4)]


def load_gl_texture(path):
    """Loads an image file and uploads it as a GL texture, returning its id."""
    image = Image.open(path).convert("RGB").transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    width, height = image.size
    data = image.tobytes()

    tex_id = GL.glGenTextures(1)
    GL.glBindTexture(GL.GL_TEXTURE_2D, tex_id)
    GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_REPEAT)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_REPEAT)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR_MIPMAP_LINEAR)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
    GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGB, width, height, 0,
                     GL.GL_RGB, GL.GL_UNSIGNED_BYTE, data)
    GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
    return tex_id
