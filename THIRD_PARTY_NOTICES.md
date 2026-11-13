# Third-party notices

| Component | Path | Author | License |
|---|---|---|---|
| Dear ImGui 1.91.7 WIP | `dll/deps/imgui/` | Omar Cornut | MIT, `dll/deps/imgui/LICENSE.txt` |
| RTX Remix API headers 0.1000.0 | `dll/deps/bridge_api/` | NVIDIA Corporation | MIT, in the file headers |

## Generated assets: Tencent Hunyuan3D 2.1 car bodies

The 3D car bodies of the cars-v3 fleet (the car archive `gta2dx9_models_cars.zip`: `assets/models/0NN_*`, built from
`assets-src/cars/models_hy/` by `tools/hy_car/hy_convert.py`; not in git) are **Output of Tencent Hunyuan3D 2.1**
(shape and texture), generated from front-right views made with Qwen-Image-Edit.

- **Licence:** Tencent Hunyuan 3D 2.1 Community License Agreement (Release Date June 13, 2025),
  https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/blob/main/LICENSE.
- **Territory exclusion:** the licence does not apply in, and grants no rights for, the **European Union, the United
  Kingdom and South Korea**. Section 5(c): the Works and their Output must not be used, reproduced, modified,
  distributed or displayed outside the Territory. Do not distribute or use the generated car models there.
- **Other Output terms:** the Output must not be used to improve any other AI model (section 5(b)); the Acceptable Use
  Policy applies.
- **What redistributors must do:** pass on a copy of the licence and this notice with the car models, and keep the
  following text in a Notice file shipped with them:
  "Tencent Hunyuan 3D 2.1 is licensed under the Tencent Hunyuan 3D 2.1 Community License Agreement, Copyright © 2025
  Tencent. All Rights Reserved. The trademark rights of “Tencent Hunyuan” are owned by Tencent or its affiliate."
- **Changed files:** every generated body was modified here (oriented, cleaned, decimated, its fused wheels cut out
  and replaced, lamp lenses and roof parts added, paint split for the game's colours) by `tools/hy_car/hy_convert.py`.

The parts the conversion adds (wheels, arch liners, lamp lenses, light bars, roof signs and their textures) are made
by `tools/hy_car/hy_convert.py` and `tools/vehicle_art2/carkit.py` in this repository. The game's own sprite art the
cars are modelled from is the publisher's and is covered by none of this (`assets/README.md`).
