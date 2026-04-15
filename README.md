# Arena → Samsung Frame TV Art Uploader (Stateless)

[![Build and Push Docker Image](https://github.com/dshatokhin/framer/actions/workflows/docker-build.yml/badge.svg)](https://github.com/dshatokhin/framer/actions/workflows/docker-build.yml)

## Overview

This system syncs images from an Are.na channel to a Samsung Frame TV's Art Mode. The solution is **stateless** - all mapping data is stored in an Are.na text block, eliminating the need for local files.

## Key Features

- **Stateless operation**: Uses Are.na as the only storage for Arena→TV mappings
- **Automatic recovery**: Detects when artwork has been removed from TV and re-uploads it
- **Continuous sync**: Can run in a loop with configurable interval
- **Image processing**: Automatically crops and resizes images to 3840×2160 (16:9)
- **CloudFront WAF bypass**: Uses `images.are.na` URLs to avoid CloudFront WAF blocks

## Architecture

- **Storage Channel**: `the_frame` - stores the "ARENA_TV_MAPPINGS" text block
- **Source Channel**: Configurable via environment variable or Are.na text block - contains image blocks to sync
- **TV**: Samsung Frame TV at `10.100.0.30`

## Files

- `sync_arena_to_tv.py` - Main sync script (self-contained)
- `requirements.txt` - Python dependencies
- `Dockerfile` - Docker image definition
- `deploy/k8s-deployment.yaml` - Kubernetes Deployment for continuous operation
- `deploy/k8s-cronjob.yaml` - Kubernetes CronJob for scheduled syncs
- `mise.toml` - Task runner configuration (replaces Makefile)
- `.env.example` - Example environment variables
- `.gitignore` - Git ignore patterns
- `README.md` - This documentation
- `inspect_tv_artwork.py` - Utility to inspect TV artwork
- `list_artworks.py` - Utility to list all TV artworks

## Quick Start

1. **Install dependencies**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Set environment variables**:
   ```bash
   export SMARTTHING_TV_IP_ADDRESS="10.100.0.30"
   export ARENA_TOKEN="your-arena-api-token"
   export ARENA_SOURCE_CHANNEL_SLUG="your-source-channel-slug"
   ```

3. **Run sync**:
   ```bash
   python3 sync_arena_to_tv.py --once
   ```

## Setup

### Prerequisites

1. Python 3.13+
2. Virtual environment (recommended)
3. Samsung Frame TV on the same network
4. Are.na API token

### Install Dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

#### Using mise.toml (Task Runner)

The Makefile has been replaced by `mise.toml` for task automation. Available tasks:

```bash
# Build Docker image
mise run build

# Run Docker container locally
mise run run
```

Install mise if not already available:
```bash
curl -fsSL https://mise.run | sh
```

### Environment Variables

Create a `.env` file or export variables:

```bash
export SMARTTHING_TV_IP_ADDRESS="10.100.0.30"
export ARENA_TOKEN="your-arena-api-token"
export ARENA_CHANNEL_SLUG="the_frame"           # Storage channel for configuration
export ARENA_SOURCE_CHANNEL_SLUG="your-source-channel-slug"  # Required: source channel slug
export SYNC_ONCE="false"                        # Set to "true" or "1" for single sync
export SYNC_INTERVAL="300"                      # Sync interval in seconds (default: 300)
```

### Text Block Configuration

The system uses text blocks in the storage channel (`ARENA_CHANNEL_SLUG`) for configuration:

1. **`ARENA_TV_MAPPINGS`** (required): Contains JSON mapping data between Are.na blocks and TV artwork IDs.
   - Created automatically on first sync
   - Stores all mapping data in JSON format

2. **`ARENA_SOURCE_CHANNEL_SLUG`** (optional but recommended): Contains the source channel slug for image blocks (required - either this block or environment variable must be set).
   - If present, this value overrides the `ARENA_SOURCE_CHANNEL_SLUG` environment variable
   - Content should be just the channel slug (e.g., `your-source-channel-slug`)
   - If not present, the environment variable is used as fallback (there is no default value)

## Usage

### Single Sync Cycle

```bash
source venv/bin/activate
python3 sync_arena_to_tv.py --once
```

### Continuous Sync (Default: 5-minute interval)

```bash
python3 sync_arena_to_tv.py
```

### Custom Interval (e.g., 10 minutes)

```bash
python3 sync_arena_to_tv.py --interval 600
```

### Specify Different Channels

```bash
ARENA_CHANNEL_SLUG="my-storage-channel" \
ARENA_SOURCE_CHANNEL_SLUG="my-images-channel" \
python3 sync_arena_to_tv.py --once
```

## Docker Deployment

The sync script can be run in a Docker container for easier deployment and isolation. See `.env.example` for required environment variables.

### Building the Image

The Docker image uses a Python slim base with runtime dependencies for Pillow image processing.

```bash
docker build -t arena-tv-sync .
```

### Running the Container

#### Single Sync Cycle

Using the `--once` flag:
```bash
docker run --rm \
  -e SMARTTHING_TV_IP_ADDRESS="10.100.0.30" \
  -e ARENA_TOKEN="your-arena-api-token" \
  arena-tv-sync --once
```

## CI/CD with GitHub Actions

The repository includes a GitHub Actions workflow that automatically builds and pushes Docker images to GitHub Container Registry (GHCR).

### Automated Workflow

On every push to the `main` branch or git tag (e.g., `v*`), the workflow:

1. **Validates code**: Checks Python syntax, installs dependencies, tests help output
2. **Builds multi-architecture images**: Creates Docker images for both `linux/amd64` and `linux/arm64`
3. **Pushes to GHCR**: Uploads images with appropriate tags:
   - `ghcr.io/dshatokhin/framer:latest` (main branch)
   - `ghcr.io/dshatokhin/framer:sha-<short-sha>` (commit references)
   - `ghcr.io/dshatokhin/framer:v1.0.0` (tagged releases)

### Pull Request Validation

Pull requests automatically run validation steps without pushing images, ensuring code quality before merging.

### Viewing Workflow Status

Check the **Actions** tab in the GitHub repository to monitor build status and view logs.

## Kubernetes Deployment

The framer can be deployed to Kubernetes using either a Deployment (continuous operation) or CronJob (scheduled syncs).

### Prerequisites

1. **Kubernetes cluster** with access to container registry
2. **TV network access**: Pods must be able to reach your Samsung Frame TV on the local network
3. **Are.na API token**: Stored as a Kubernetes Secret

### Building and Pushing the Image

**Automated via GitHub Actions**: Docker images are automatically built and pushed to GHCR on every push to `main`. The images are available at `ghcr.io/dshatokhin/framer:latest`.

**Manual build** (if needed):

```bash
# Build the image
docker build -t ghcr.io/dshatokhin/framer:latest .

# Push to GitHub Container Registry (GHCR)
docker push ghcr.io/dshatokhin/framer:latest
```

### Configuration

Create a Kubernetes Secret with your Are.na API token:

```bash
kubectl create secret generic framer-secrets \
  --from-literal=arena-token='your-arena-api-token'
```

### Option 1: Deployment (Continuous Operation)

Use this for continuous sync with configurable intervals. The container runs continuously and syncs at the specified interval.

```bash
# Apply the deployment
kubectl apply -f deploy/k8s-deployment.yaml
```

Edit `deploy/k8s-deployment.yaml` to configure:
- `SMARTTHING_TV_IP_ADDRESS`: Your TV's IP address
- `ARENA_SOURCE_CHANNEL_SLUG`: Your Are.na source channel slug
- Other environment variables as needed

### Option 2: CronJob (Scheduled Syncs)

Use this for scheduled syncs (e.g., every 5 minutes, hourly). More resource-efficient than continuous operation.

```bash
# Apply the cronjob
kubectl apply -f deploy/k8s-cronjob.yaml
```

Edit `deploy/k8s-cronjob.yaml` to configure:
- `schedule`: Cron schedule expression (e.g., `*/5 * * * *` for every 5 minutes)
- `SMARTTHING_TV_IP_ADDRESS`: Your TV's IP address
- `ARENA_SOURCE_CHANNEL_SLUG`: Your Are.na source channel slug

### Network Considerations

If your TV is on the same network as your Kubernetes nodes, you may need to:
1. **Use hostNetwork**: Uncomment `hostNetwork: true` in the YAML files
2. **Configure network policies**: Allow pods to access the TV's IP address
3. **Use NodeSelector**: Schedule pods on specific nodes with TV network access

### Monitoring

Check the status of your deployment:

```bash
# For Deployment
kubectl get deployment framer
kubectl get pods -l app=framer
kubectl logs -l app=framer --tail=50

# For CronJob
kubectl get cronjob framer-cronjob
kubectl get jobs --selector=job-name=framer-cronjob-*
kubectl logs -l app=framer --tail=50
```

## How It Works

1. **Load mappings**: Fetches the "ARENA_TV_MAPPINGS" text block from the storage channel
2. **Validate TV state**: Checks which mapped artworks still exist on the TV
3. **Remove invalid mappings**: Deletes mappings for artworks no longer on the TV
4. **Fetch Arena blocks**: Loads image blocks from the source channel
5. **Identify unuploaded**: Finds blocks without mappings or with invalid mappings
6. **Process & upload**: Downloads, crops/resizes, and uploads each image
7. **Update mappings**: Saves updated mappings back to Are.na after each upload

## TV Artwork IDs

- **Uploaded artwork**: IDs like `MY_F0030`, `MY_F0031` (with underscore)
- **Built-in artwork**: IDs like `SAM-F0103`, `SAM-F0104` (with hyphen)

## Source Channel Consistency

The system automatically handles changes to the source channel:

1. **Configuration**: The source channel slug can be stored in an Are.na text block titled `ARENA_SOURCE_CHANNEL_SLUG` in the storage channel
2. **Change Detection**: When the source channel changes (either via environment variable or Are.na block), the system detects the change
3. **Automatic Cleanup**: All existing TV artwork is deleted and mappings are cleared
4. **Fresh Start**: New artwork is uploaded from the new source channel

This ensures that switching to a different Are.na channel doesn't leave old artwork on the TV.

## Troubleshooting

### Check TV Connection

```bash
python3 inspect_tv_artwork.py
```

### List All TV Artworks

```bash
python3 list_artworks.py
```

### Verify Are.na API

```bash
python3 -c "
import os, requests
token = os.getenv('ARENA_TOKEN')
headers = {'Authorization': f'Bearer {token}'}
r = requests.get('https://api.are.na/v3/channels/the_frame', headers=headers)
print(f'Status: {r.status_code}')
"
```

### Common Issues

1. **Missing dependencies**: Run `pip install -r requirements.txt`
2. **TV not reachable**: Verify IP address and network connectivity
3. **Are.na API errors**: Check token validity and channel permissions
4. **Image download failures**: Script uses fallback URLs to bypass CloudFront WAF

## Development

### Testing

The script includes comprehensive logging. For verbose output, modify the logging level in `sync_arena_to_tv.py`:

```python
logging.basicConfig(level=logging.DEBUG, ...)
```

### Adding New Features

- The script is self-contained in a single file
- All Are.na API interactions use the v3 endpoints
- TV communication uses the `samsungtvws` library

## Legacy Files

Old scripts and test files have been removed to keep the repository tidy. The system is now fully stateless with all configuration and mapping data stored in Are.na blocks.

## License

MIT
