<#
.SYNOPSIS
    Extracts the ComfyUI prompt and workflow embedded in a generated PNG.

.DESCRIPTION
    ComfyUI stores two text chunks inside every image it saves: `prompt`
    is the graph in API form, exactly as it was submitted, and `workflow`
    is the same graph in editor form, with node positions. Both are plain
    JSON, so a frame carries everything needed to reproduce or reopen it.

    By default the function returns the readable summary: model, LoRAs,
    seed, steps, sampler, size and every text found in prompt-encoding
    nodes. Use -Raw for the JSON itself, or -SaveWorkflow to write out a
    json file that can be dragged straight into the ComfyUI canvas.

    Only frames queued from the ComfyUI interface carry the `workflow`
    chunk. Anything submitted through the API — every frame produced by
    our generation scripts — has the `prompt` graph and nothing else, so
    -SaveWorkflow warns and writes no file. The API graph still holds the
    model, prompt text and all sampler settings.

    Note that a frame regenerated with the same seed is pixel identical
    but not byte identical: these chunks differ, because the filename
    prefix is part of the stored graph. Compare pixels, not hashes.

.PARAMETER Path
    One or more PNG files. Accepts pipeline input from Get-ChildItem.

.PARAMETER Raw
    Return the `prompt` and `workflow` JSON strings instead of a summary.

.PARAMETER SaveWorkflow
    Folder (or single file name) to write the extracted workflow JSON to.

.EXAMPLE
    Get-PngPrompt \\ranma\ComfyUI\output\portrait-flux2-dev-r03-i10b_00001_.png

.EXAMPLE
    Get-ChildItem \\ranma\ComfyUI\output\portrait-*.png | Get-PngPrompt |
        Format-Table Name, Model, Seed, Steps

.EXAMPLE
    Get-ChildItem *.png | Get-PngPrompt -SaveWorkflow C:\temp\workflows
#>
function Get-PngPrompt {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, ValueFromPipeline, ValueFromPipelineByPropertyName)]
        [Alias('FullName')]
        [string[]] $Path,

        [switch] $Raw,

        [string] $SaveWorkflow
    )

    process {
        foreach ($file in $Path) {
            $item = Get-Item -LiteralPath $file -ErrorAction Stop
            $chunks = Read-PngTextChunk -Path $item.FullName

            if ($SaveWorkflow) {
                if ($chunks.ContainsKey('workflow') -and $chunks['workflow']) {
                    $target = if (Test-Path -LiteralPath $SaveWorkflow -PathType Container) {
                        Join-Path $SaveWorkflow ($item.BaseName + '.json')
                    }
                    else {
                        $SaveWorkflow
                    }
                    [System.IO.File]::WriteAllText(
                        $target, $chunks['workflow'],
                        (New-Object System.Text.UTF8Encoding $false))
                    Write-Verbose "workflow saved to $target"
                }
                else {
                    Write-Warning ("$($item.Name): no workflow chunk. Frames queued " +
                        "through the API carry only the `prompt` graph; the editor " +
                        "workflow is stored only for jobs started from the ComfyUI UI.")
                }
            }

            if ($Raw) {
                [pscustomobject] @{
                    Name     = $item.Name
                    Prompt   = $chunks['prompt']
                    Workflow = $chunks['workflow']
                    Path     = $item.FullName
                }
                continue
            }

            $graph = $null
            if ($chunks.ContainsKey('prompt')) {
                $graph = $chunks['prompt'] | ConvertFrom-Json
            }

            $texts = @()
            $loras = @()
            $model = $null
            $seed = $null
            $steps = $null
            $sampler = $null
            $guidance = $null
            $width = $null
            $height = $null

            if ($graph) {
                foreach ($name in $graph.PSObject.Properties.Name) {
                    $node = $graph.$name
                    $in = $node.inputs
                    switch -Wildcard ($node.class_type) {
                        'CLIPTextEncode*' {
                            if ($in.text -is [string] -and $in.text.Trim()) { $texts += $in.text }
                        }
                        'UNETLoader'        { $model = $in.unet_name }
                        'CheckpointLoader*' { $model = $in.ckpt_name }
                        'LoraLoader*'       { $loras += '{0}:{1}' -f $in.lora_name, $in.strength_model }
                        'RandomNoise'       { $seed = $in.noise_seed }
                        'KSamplerSelect'    { $sampler = $in.sampler_name }
                        'FluxGuidance'      { $guidance = $in.guidance }
                        'KSampler*' {
                            if ($null -ne $in.seed)         { $seed = $in.seed }
                            if ($null -ne $in.steps)        { $steps = $in.steps }
                            if ($null -ne $in.sampler_name) { $sampler = $in.sampler_name }
                            if ($null -ne $in.cfg)          { $guidance = $in.cfg }
                        }
                        '*Scheduler' {
                            if ($null -ne $in.steps) { $steps = $in.steps }
                        }
                        '*LatentImage' {
                            if ($null -ne $in.width)  { $width = $in.width }
                            if ($null -ne $in.height) { $height = $in.height }
                        }
                    }
                }
            }

            $size = $null
            if ($width) { $size = '{0}x{1}' -f $width, $height }

            [pscustomobject] @{
                Name        = $item.Name
                Model       = $model
                Loras       = $loras
                Seed        = $seed
                Steps       = $steps
                Guidance    = $guidance
                Sampler     = $sampler
                Size        = $size
                Texts       = $texts
                Prompt      = $texts | Select-Object -First 1
                HasGraph    = [bool] $graph
                HasWorkflow = [bool] $chunks['workflow']
                Path        = $item.FullName
            }
        }
    }
}
