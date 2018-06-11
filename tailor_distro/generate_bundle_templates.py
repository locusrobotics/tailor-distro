#!/usr/bin/python3
import jinja2
import pathlib


def main():
    context = {
        'distro': 'ubuntu',
        'codename': 'xenial',
        'bundle_name': 'developer',
        'build_deps': 'asdf,fdsa',
        'run_deps': 'asdf,fdsa',
    }

    env = jinja2.Environment(
        loader=jinja2.PackageLoader('tailor_distro', 'debian_templates'),
        undefined=jinja2.StrictUndefined
    )

    workspace_path = pathlib.Path('workspace/src')

    for template_name in env.list_templates():
        output_path = workspace_path / template_name

        output_path.parent.mkdir(parents=True, exist_ok=True)

        template = env.get_template(template_name)
        stream = template.stream(**context)
        stream.dump(str(output_path))


if __name__ == '__main__':
    main()
