# ecr-ops
Operations Scripts for managing ecr registries. ECR limits 1000 images per amazon account. This script helps prune images based on different criteria.

## pruneBuilds.py
Python class to prune builds from all branches in a repository.
Keeps images based on the following criteria:
 - last 10 images for 'develop' branch
 - last 10 images for 'master' branch
 - last 2 images for 'feature' branch
 - last 3 verions builds for both 'rc' and 'versions'

## registry_ops.py
Handler for instantiating pruneBuilds. Checks if environment variables are set and proceeds
to call PruneBuilds class.

### Execution setps
```bash
1. In docker-compose.yml, set REGISTRY from which you want to prune the builds
2. docker-compose up
3. pytest test_registry_ops.py
```


