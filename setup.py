from setuptools import find_packages, setup

setup(
    name="graspkg",
    version="0.1.0",
    description="Perception-grounded, affordance-aware knowledge graph for grasp reasoning on the Toyota HSR.",
    packages=find_packages(include=["graspkg", "graspkg.*"]),
    include_package_data=True,
    package_data={"graspkg": ["ontology/*.ttl"]},
    install_requires=["rdflib>=7.0", "owlrl>=6.0", "numpy>=1.24"],
    python_requires=">=3.8",
)
