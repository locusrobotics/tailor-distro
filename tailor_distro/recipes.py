import yaml

from dataclasses import dataclass, field
from typing import List, Dict, Any, Set
from pathlib import Path


@dataclass
class Distribution:
    name: str
    os: List[str] = field(default_factory=list)
    env: Dict[str, Any] = field(default_factory=dict)
    upstream: Dict[str, str] = field(default_factory=dict)
    compat_catkin_tools: bool = False
    underlays: List[str] = field(default_factory=list)
    root_packages: List[str] = field(default_factory=list)


@dataclass
class Recipe:
    """
    A single receipe. Unique information for this recipe such as the flavour

    """

    flavour: str
    distributions: Dict[str, Distribution]
    description: str
    # TODO: Do we need these?
    os_name: str
    os_version: str
    path: Path
    release_label: str
    release_track: str

    # Maybe there's a better way to do this. But initializing dataclasses from
    # dictionary kwargs doesn't follow nested dicts so the types don't come out
    # correct. For now there is only the Distribution type so handle that
    # manually
    def __post_init__(self):
        for name, distribution in self.distributions.copy().items():
            if isinstance(distribution, Distribution):
                continue

            self.distributions[name] = Distribution(name=name, **distribution)


@dataclass
class GlobalRecipe:
    """
    The information (recipe) needed to build all packages for a given
    OS/distro. This will be a combined set of all receipes being built.
    """

    os_name: str
    os_version: str
    cxx_flags: List[str]
    cxx_standard: str
    default_build_depends: List[str]
    distributions: Dict[str, Distribution]
    docker_registry: str
    organization: str
    python_version: str
    flavour: str
    build_flavour: str
    cloudfront_distribution_id: str
    apt_region: str
    apt_repo: str
    testing_flavour: str
    vendor_environments: str
    build_date: str

    recipes: List[Recipe] = field(default_factory=list)

    def __post_init__(self):
        for name, distribution in self.distributions.copy().items():
            if isinstance(distribution, Distribution):
                continue

            self.distributions[name] = Distribution(name=name, **distribution)

    def __hash__(self):
        return hash((self.os_name, self.os_version))

    def add_recipe(self, recipe: Recipe):
        self.recipes.append(recipe)

    @property
    def root_packages(self) -> Dict[str, Set[str]]:
        """
        Gets root_packages for all recipes within this global recipe
        """
        ret: Dict[str, Set[str]] = {}

        for recipe in self.recipes:
            for name, distribution in recipe.distributions.items():
                if distribution.root_packages is None:
                    continue

                if name not in ret:
                    ret[name] = set()

                for pkg in distribution.root_packages:
                    ret[name].add(pkg)
        return ret

    @property
    def release_label(self):
        label = None

        for recipe in self.recipes:
            if label is None:
                label = recipe.release_label

            if recipe.release_label != label:
                raise Exception(
                    f"The recipe {recipe.flavour} release label "
                    f"{recipe.release_label} is inconsistent with other recipes!"
                )

        return label


def load_recipes(path: Path) -> List[GlobalRecipe]:
    """
    Loads all recipes from a folder on disk.
    """
    if not path.is_dir():
        raise Exception(f"{path} is not directory!")

    recipe_data: Dict[str, Any] = {}
    global_recipes: List[GlobalRecipe] = []

    # Load up all the recipe data
    for file in path.iterdir():
        data = yaml.safe_load(file.read_text())

        os_name = data["os_name"]
        os_version = data["os_version"]
        flavour = data["flavour"]

        if os_name not in recipe_data:
            recipe_data[os_name] = {}

        if os_version not in recipe_data[os_name]:
            recipe_data[os_name][os_version] = {}

        recipe_data[os_name][os_version][flavour] = data

    # Convert the recipe data into classes for convenience
    for os_name, os_versions in recipe_data.items():
        for os_version, recipes in os_versions.items():
            # First get the common components to create a global recipe class
            common = recipes.get("common", None)
            if common is None:
                raise Exception("A common recipe must be provided!")

            global_recipe = GlobalRecipe(**common)

            del recipes["common"]

            # For each recipe add it to the global class
            for flavour, data in recipes.items():
                recipe = Recipe(**data)

                global_recipe.add_recipe(recipe)

            global_recipes.append(global_recipe)

    return global_recipes
