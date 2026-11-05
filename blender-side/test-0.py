import bpy, json, base64, math
import numpy as np
from typing import Any
from mathutils import Matrix

# Blender -> Unity: (x, y, z) -> (x, z, -y)
C = Matrix.Rotation(-math.pi / 2, 4, 'X')
C_INV = C.inverted()
MATRIX_LAYOUT = "column-major"

BoneWeights = list[tuple[int, float]]


# ==================================================
# Utilities
# ==================================================

def read_array(collection: Any, prop: str, width: int = 1, dtype: Any = np.float32) -> np.ndarray:
    result = np.empty(len(collection) * width, dtype=dtype)
    if result.size:
        collection.foreach_get(prop, result)
    return result.reshape(-1, width) if width > 1 else result


def convert_vectors(array: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(array[:, [0, 2, 1]] * [1, 1, -1], dtype="<f4")


def convert_matrix(matrix: Matrix) -> Matrix:
    return C @ matrix @ C_INV


def matrix_array(matrices: list[Matrix]) -> np.ndarray:
    if not matrices:
        return np.empty((0, 16), dtype="<f4")
    # BLUN stores matrices column-major. Unity Matrix4x4 uses the same element order.
    return np.asarray([np.asarray(m, dtype="<f4").T.reshape(16) for m in matrices], dtype="<f4")


def identity_matrix_array() -> np.ndarray:
    return matrix_array([Matrix.Identity(4)])


def validate_object(obj: bpy.types.Object) -> None:
    if obj is None or obj.type != "MESH" or obj not in bpy.context.selected_objects:
        raise ValueError("Select and activate a mesh object.")


# ==================================================
# Armature and modifier handling
# ==================================================

def find_armature(obj: bpy.types.Object) -> tuple[bpy.types.Object | None, bpy.types.Modifier | None]:
    modifiers = [m for m in obj.modifiers if m.type == "ARMATURE"]
    if not modifiers:
        return None, None
    if len(modifiers) != 1:
        raise ValueError(f"Only one Armature Modifier is supported; found {len(modifiers)}.")

    modifier = modifiers[0]
    if modifier.object is None or modifier.object.type != "ARMATURE":
        raise ValueError(f"Armature Modifier '{modifier.name}' has no valid Armature Object.")
    if not modifier.use_vertex_groups:
        raise ValueError(f"Armature Modifier '{modifier.name}' must use Vertex Groups.")
    if modifier.use_bone_envelopes:
        raise ValueError(f"Armature Modifier '{modifier.name}': Bone Envelopes are not supported.")
    if modifier.use_multi_modifier:
        raise ValueError(f"Armature Modifier '{modifier.name}': Multi Modifier is not supported.")

    return modifier.object, modifier


def get_evaluated_mesh_without_armature(obj: bpy.types.Object) -> tuple[bpy.types.Object, bpy.types.Mesh, list[tuple[bpy.types.Modifier, bool]]]:
    armature_modifiers = [m for m in obj.modifiers if m.type == "ARMATURE"]
    previous_states = [(m, m.show_viewport) for m in armature_modifiers]
    evaluated_obj = None
    evaluated_mesh = None

    try:
        for modifier, _ in previous_states:
            modifier.show_viewport = False

        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated_obj = obj.evaluated_get(depsgraph)
        evaluated_mesh = evaluated_obj.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)

        if evaluated_mesh is None:
            raise RuntimeError("Could not evaluate mesh.")

        # Keep Armature modifiers disabled until the caller finishes reading this evaluated mesh.
        return evaluated_obj, evaluated_mesh, previous_states
    except Exception:
        if evaluated_obj is not None and evaluated_mesh is not None:
            evaluated_obj.to_mesh_clear()
        for modifier, show_viewport in previous_states:
            modifier.show_viewport = show_viewport
        bpy.context.view_layer.update()
        raise

# ==================================================
# Skeleton
# ==================================================

def build_skeleton(obj: bpy.types.Object, armature: bpy.types.Object | None) -> tuple[list[dict[str, Any]], list[Matrix], list[Matrix], list[int]]:
    if armature is None:
        return [], [], [], []

    bones = list(armature.data.bones)
    bone_map = {bone.name: i for i, bone in enumerate(bones)}
    mesh_inv = obj.matrix_world.inverted_safe()

    global_matrices = [
        mesh_inv @ armature.matrix_world @ bone.matrix_local
        for bone in bones
    ]

    local_matrices: list[Matrix] = []
    bindposes: list[Matrix] = []
    bone_info: list[dict[str, Any]] = []
    root_bones: list[int] = []

    for i, bone in enumerate(bones):
        parent = bone_map[bone.parent.name] if bone.parent else -1
        if parent >= 0:
            local = global_matrices[parent].inverted_safe() @ global_matrices[i]
        else:
            local = global_matrices[i]
            root_bones.append(i)

        local_matrices.append(convert_matrix(local))
        bindposes.append(convert_matrix(global_matrices[i].inverted_safe()))
        bone_info.append({"name": bone.name, "parent": parent, "useDeform": bool(bone.use_deform)})

    return bone_info, local_matrices, bindposes, root_bones


# ==================================================
# Mesh attributes
# ==================================================

def build_mesh_attributes(mesh: bpy.types.Mesh) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[np.ndarray], np.ndarray, list[np.ndarray], list[dict[str, str]]]:
    mesh.calc_loop_triangles()

    uv_layers = list(mesh.uv_layers)
    if uv_layers and len(mesh.polygons):
        mesh.calc_tangents(uvmap=mesh.uv_layers.active.name if mesh.uv_layers.active else uv_layers[0].name)

    positions = convert_vectors(read_array(mesh.vertices, "co", 3))
    loop_vertices = read_array(mesh.loops, "vertex_index", dtype=np.int32)
    normals = convert_vectors(read_array(mesh.loops, "normal", 3))

    if uv_layers:
        uvs = [read_array(layer.data, "uv", 2) for layer in uv_layers]
    else:
        uvs = []

    if uv_layers and len(mesh.polygons):
        tangents = convert_vectors(read_array(mesh.loops, "tangent", 3))
        tangent_signs = read_array(mesh.loops, "bitangent_sign")
    else:
        tangents = np.zeros((len(mesh.loops), 3), dtype="<f4")
        tangent_signs = np.ones(len(mesh.loops), dtype="<f4")

    color_arrays: list[np.ndarray] = []
    color_info: list[dict[str, str]] = []

    for color_attr in mesh.color_attributes:
        if color_attr.data_type not in {"FLOAT_COLOR", "BYTE_COLOR"}:
            continue
        if color_attr.domain not in {"POINT", "CORNER"}:
            raise ValueError(
                f"Color attribute '{color_attr.name}' uses unsupported domain '{color_attr.domain}'. "
                "Only POINT and CORNER are supported."
            )

        values = read_array(color_attr.data, "color", 4)
        if color_attr.domain == "POINT":
            values = values[loop_vertices]

        color_arrays.append(np.ascontiguousarray(values, dtype="<f4"))
        color_info.append({
            "name": color_attr.name,
            "attribute": f"color{len(color_arrays) - 1}",
            "domain": color_attr.domain
        })

    return positions, loop_vertices, normals, tangents, uvs, tangent_signs, color_arrays, color_info


def build_vertices(mesh: bpy.types.Mesh, attributes: tuple) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    positions, loop_vertices, normals, tangents, uvs, tangent_signs, color_arrays, _ = attributes

    tri_loops = read_array(mesh.loop_triangles, "loops", 3, np.int32).reshape(-1)
    source_vertices = loop_vertices[tri_loops]

    parts = [
        positions[source_vertices],
        normals[tri_loops],
        tangents[tri_loops],
        tangent_signs[tri_loops, None]
    ]
    parts.extend(uv[tri_loops] for uv in uvs)
    parts.extend(color[tri_loops] for color in color_arrays)
    corner_attributes = np.column_stack(parts).astype("<f4", copy=False)

    # Include original vertex index to preserve separate source vertices at coincident positions.
    source_key = np.ascontiguousarray(source_vertices, dtype="<i4").view(np.uint8).reshape(-1, 4)
    attribute_key = np.ascontiguousarray(corner_attributes).view(np.uint8).reshape(len(corner_attributes), -1)
    keys = np.concatenate((source_key, attribute_key), axis=1)

    _, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    order = np.argsort(first, kind="stable")
    first = first[order]

    remap = np.empty(len(order), dtype=np.uint32)
    remap[order] = np.arange(len(order), dtype=np.uint32)
    indices = remap[inverse]

    triangle_polygons = read_array(mesh.loop_triangles, "polygon_index", dtype=np.int32)
    return corner_attributes[first], source_vertices[first], indices, triangle_polygons


# ==================================================
# Submeshes
# ==================================================

def build_submeshes(mesh: bpy.types.Mesh, indices: np.ndarray, triangle_polygons: np.ndarray) -> tuple[list[dict[str, int]], np.ndarray]:
    polygon_materials = read_array(mesh.polygons, "material_index", dtype=np.int32)
    triangle_materials = polygon_materials[triangle_polygons]
    corner_materials = np.repeat(triangle_materials, 3)

    submeshes: list[dict[str, int]] = []
    index_parts: list[np.ndarray] = []
    index_start = 0

    for material_index in np.unique(triangle_materials):
        part = indices[corner_materials == material_index]
        submeshes.append({
            "indexStart": index_start,
            "indexCount": len(part),
            "materialIndex": int(material_index)
        })
        index_parts.append(part)
        index_start += len(part)

    return submeshes, np.concatenate(index_parts) if index_parts else np.empty(0, dtype=np.uint32)


# ==================================================
# Skinning
# ==================================================

def build_weights(mesh: bpy.types.Mesh, obj: bpy.types.Object, armature: bpy.types.Object | None, source_vertices: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    weight_dtype = np.dtype([("boneIndex", "<i4"), ("weight", "<f4")])
    if armature is None:
        return np.zeros(len(source_vertices), dtype=np.uint8), np.empty(0, dtype=weight_dtype)

    bones = list(armature.data.bones)
    bone_map = {bone.name: i for i, bone in enumerate(bones) if bone.use_deform}
    group_map = {group.index: bone_map[group.name] for group in obj.vertex_groups if group.name in bone_map}

    bones_per_vertex = np.zeros(len(source_vertices), dtype=np.uint8)
    weight_cache: dict[int, BoneWeights] = {}
    flat_indices: list[int] = []
    flat_weights: list[float] = []
    unweighted: list[int] = []

    for i, source_index in enumerate(source_vertices):
        source_index = int(source_index)

        if source_index not in weight_cache:
            weights = [
                (group_map[group.group], float(group.weight))
                for group in mesh.vertices[source_index].groups
                if group.group in group_map and group.weight > 0 and math.isfinite(group.weight)
            ]
            weights.sort(key=lambda item: item[1], reverse=True)

            total = sum(weight for _, weight in weights)
            if total > 0:
                weights = [(bone, weight / total) for bone, weight in weights]
            else:
                unweighted.append(source_index)

            if len(weights) > 255:
                raise ValueError(f"Vertex {source_index} has more than 255 bone influences.")

            weight_cache[source_index] = weights

        weights = weight_cache[source_index]
        bones_per_vertex[i] = len(weights)
        for bone_index, weight in weights:
            flat_indices.append(bone_index)
            flat_weights.append(weight)

    if unweighted:
        sample = ", ".join(map(str, sorted(set(unweighted))[:20]))
        suffix = " ..." if len(set(unweighted)) > 20 else ""
        raise ValueError(f"{len(set(unweighted))} exported vertices have no valid deform-bone weights. Vertex indices: {sample}{suffix}")

    weights = np.empty(len(flat_indices), dtype=weight_dtype)
    weights["boneIndex"] = flat_indices
    weights["weight"] = flat_weights
    return bones_per_vertex, weights


# ==================================================
# Binary packing
# ==================================================

def pack_attributes(attributes: dict[str, tuple[np.ndarray, int, str | None]]) -> tuple[dict[str, dict[str, Any]], bytes]:
    metadata: dict[str, dict[str, Any]] = {}
    chunks: list[bytes] = []
    offset = 0

    for name, (array, count, fmt) in attributes.items():
        array = np.ascontiguousarray(array)
        padding = (-offset) % 4
        if padding:
            chunks.append(b"\0" * padding)
            offset += padding

        entry: dict[str, Any] = {"start": offset, "count": int(count)}
        if fmt:
            entry["format"] = fmt
        metadata[name] = entry

        raw = array.tobytes()
        chunks.append(raw)
        offset += array.nbytes

    return metadata, b"".join(chunks)


# ==================================================
# Main exporter
# ==================================================

def export_blun(context: bpy.types.Context, filepath: str) -> None:
    obj = context.view_layer.objects.active
    validate_object(obj)

    armature, armature_modifier = find_armature(obj)
    bones, bone_local, bindposes, root_bones = build_skeleton(obj, armature)

    evaluated_obj = None
    evaluated_mesh = None
    previous_modifier_states = []
    try:
        evaluated_obj, evaluated_mesh, previous_modifier_states = get_evaluated_mesh_without_armature(obj)
        mesh = evaluated_mesh

        mesh_attributes = build_mesh_attributes(mesh)
        vertex_attributes, source_vertices, indices, triangle_polygons = build_vertices(mesh, mesh_attributes)
        submeshes, indices = build_submeshes(mesh, indices, triangle_polygons)
        vertex_count = len(vertex_attributes)

        index_format = "uint16" if vertex_count <= 65536 else "uint32"
        indices = indices.astype("<u2" if index_format == "uint16" else "<u4")

        bones_per_vertex, weights = build_weights(mesh, obj, armature, source_vertices)

        # Attribute layout: position(3), normal(3), tangent(4), UV maps(2 each), colors(4 each).
        offset = 0
        attributes_to_pack: dict[str, tuple[np.ndarray, int, str | None]] = {}

        attributes_to_pack["position"] = (vertex_attributes[:, offset:offset + 3].astype("<f4"), vertex_count, None)
        offset += 3
        attributes_to_pack["normal"] = (vertex_attributes[:, offset:offset + 3].astype("<f4"), vertex_count, None)
        offset += 3
        attributes_to_pack["tangent"] = (vertex_attributes[:, offset:offset + 4].astype("<f4"), vertex_count, None)
        offset += 4

        uv_info = []
        for i, _ in enumerate(mesh.uv_layers):
            attributes_to_pack[f"uv{i}"] = (vertex_attributes[:, offset:offset + 2].astype("<f4"), vertex_count, None)
            uv_info.append({"name": mesh.uv_layers[i].name, "attribute": f"uv{i}"})
            offset += 2

        color_info = mesh_attributes[7]
        for i, info in enumerate(color_info):
            attributes_to_pack[f"color{i}"] = (vertex_attributes[:, offset:offset + 4].astype("<f4"), vertex_count, None)
            offset += 4

        if offset != vertex_attributes.shape[1]:
            raise RuntimeError("Internal vertex attribute layout mismatch.")

        attributes_to_pack.update({
            "indices": (indices, len(indices), index_format),
            "bonesPerVertex": (bones_per_vertex, vertex_count, None),
            "weights": (weights, len(weights), "int32_float32"),
            "objectMatrix": (matrix_array([convert_matrix(obj.matrix_world)]), 1, "float32x16"),
            "boneLocalMatrices": (matrix_array(bone_local), len(bone_local), "float32x16"),
            "bindposes": (matrix_array(bindposes), len(bindposes), "float32x16")
        })

        attributes, binary_data = pack_attributes(attributes_to_pack)

        data: dict[str, Any] = {
            "version": 2,
            "name": obj.name,
            "coordinateSystem": "Unity",
            "matrixLayout": MATRIX_LAYOUT,
            "skeletonContainer": {
                "name": armature.name if armature else f"{obj.name}_Skeleton",
                "parent": "mesh",
                "localMatrix": "identity"
            },
            "rootBones": root_bones,
            "bones": bones,
            "uvLayers": uv_info,
            "colorAttributes": color_info,
            "attributes": attributes,
            "submeshes": submeshes,
            "data": base64.b64encode(binary_data).decode("ascii")
        }

        with open(filepath, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4, ensure_ascii=False)

        print(f"BLUN exported: {filepath}")
        print(f"Vertices: {vertex_count} | Indices: {len(indices)} | Submeshes: {len(submeshes)}")
        print(f"Bones: {len(bones)} | Root bones: {len(root_bones)} | Influences: {len(weights)}")
        print(f"UV maps: {len(uv_info)} | Color attributes: {len(color_info)}")
        print(f"Matrix layout: {MATRIX_LAYOUT}")
        print(f"Binary size: {len(binary_data):,} bytes")
    finally:
        if evaluated_obj is not None and evaluated_mesh is not None:
            evaluated_obj.to_mesh_clear()
        for modifier, show_viewport in previous_modifier_states:
            modifier.show_viewport = show_viewport
        bpy.context.view_layer.update()


obj = bpy.context.view_layer.objects.active
if obj:
    export_blun(bpy.context, bpy.path.abspath(f"//{obj.name}.blun"))
