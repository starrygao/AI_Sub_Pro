"""Keep the healthy current AI Sub Pro image and one rollback; no global prune."""
import argparse
import json
import subprocess

REPOSITORY='ai-sub-pro'


def command(*args):
    return subprocess.check_output(['docker',*args],text=True).strip()


def plan(images,containers,current_id):
    used={c['image'] for c in containers}
    used_refs={c['ref'] for c in containers}
    previous=next((i['id'] for i in images if REPOSITORY+':rollback' in i['tags'] and i['id']!=current_id),None)
    protected=used_refs|{REPOSITORY+':rollback'}
    for item in images:
        tags=sorted(tag for tag in item['tags'] if tag.startswith(REPOSITORY+':'))
        if item['id'] in used and tags and not protected.intersection(tags):protected.add(tags[0])
    remove=sorted({tag for item in images for tag in item['tags']
                   if tag.startswith(REPOSITORY+':') and tag not in protected})
    return {'current':current_id,'rollback':previous,'remove_tags':remove}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    ids=command('image','ls',REPOSITORY,'--no-trunc','--quiet').splitlines()
    images=[]
    for image_id in sorted(set(ids)):
        value=json.loads(command('image','inspect',image_id,'--format','{{json .}}'))
        images.append({'id':value['Id'],'tags':value.get('RepoTags') or [],'created':value['Created']})
    containers=[]
    for container_id in command('ps','-aq').splitlines():
        image=command('inspect',container_id,'--format','{{.Image}}')
        ref=command('inspect',container_id,'--format','{{.Config.Image}}')
        containers.append({'image':image,'ref':ref})
    current=command('inspect','ai-sub-pro','--format','{{.Image}}')
    health=command('inspect','ai-sub-pro','--format','{{.State.Health.Status}}')
    result=plan(images,containers,current)
    if args.apply:
        if health!='healthy':raise RuntimeError('Current service must be healthy before retiring images')
        if not result['rollback']:raise RuntimeError('Tag the previously verified release as ai-sub-pro:rollback first')
        result['removed_tags']=[]
        for tag in result['remove_tags']:
            command('image','rm',tag)  # No force: Docker protects referenced images.
            result['removed_tags'].append(tag)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
