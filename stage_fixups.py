"""Non-destructive session-layer fixes so poorly-authored assets render sensibly in Hydra."""
import os

from pxr import Usd, UsdShade, UsdLux

ENV_TEXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "env.png")
DOME_PATH = "/__viewer_dome"


def apply_missing_binding_apis(stage):
    """Hydra ignores `material:binding` on prims lacking MaterialBindingAPI
    (renders default gray). Apply the schema where it's missing."""
    count = 0
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        for prim in stage.Traverse():
            if prim.HasAPI(UsdShade.MaterialBindingAPI):
                continue
            if any(r.GetName().startswith("material:binding") for r in prim.GetRelationships()):
                UsdShade.MaterialBindingAPI.Apply(prim)
                count += 1
    return count


def add_default_dome(stage):
    """Metallic/dark PBR materials render near-black without an environment.
    Add a textured dome light (also drawn as the backdrop by Hydra)."""
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        dome = UsdLux.DomeLight.Define(stage, DOME_PATH)
        dome.CreateIntensityAttr(1.0)
        dome.CreateTextureFileAttr(ENV_TEXTURE.replace("\\", "/"))
        dome.CreateTextureFormatAttr("latlong")
