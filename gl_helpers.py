def to_gl_matrix(matrix4d):
    """Column-major flattening of a Gf.Matrix4d (row-vector convention) into
    the layout glLoadMatrixd expects for column-vector GL math -- i.e. the
    transpose of Gf's row-major storage, transposed by hand here rather than
    via glLoadTransposeMatrixd, which some drivers (e.g. Intel/Windows) accept
    without error but silently fail to apply."""
    rows = [list(row) for row in matrix4d]
    return [rows[col][row] for col in range(4) for row in range(4)]
