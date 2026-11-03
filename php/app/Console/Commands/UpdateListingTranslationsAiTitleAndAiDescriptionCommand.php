<?php

namespace App\Console\Commands;

use App\Entities\Language;
use App\Entities\ListingTranslation;
use Illuminate\Console\Command;

class UpdateListingTranslationsAiTitleAndAiDescriptionCommand extends Command
{
    /**
     * The name and signature of the console command.
     *
     * @var string
     */
    protected $signature = 'listing-translations:generate-ai-content {--limit=100}';

    /**
     * The console command description.
     *
     * @var string
     */
    protected $description = 'Generate AI titles and descriptions for listing translations';

    protected $client;

    /**
     * Execute the console command.
     */
    public function handle()
    {
        $startTime = microtime(true);

        $this->client = $this->resolveOpenAiClient();

        $limit = $this->option('limit');

        // Get English language ID
        $englishLanguage = Language::where('code', 'en')->first();
        if (!$englishLanguage) {
            $this->error('English language not found in database.');
            return;
        }

        // Get all listing translations that need AI content (English only)
        $translations = ListingTranslation::select([
            'id',
            'language_id',
            'title',
            'needs_ai_title',
            'description',
            'needs_ai_description'
        ])
        ->where('language_id', $englishLanguage->id)
        ->where(function ($query) {
            $query->where('needs_ai_title', 1)
                  ->orWhere('needs_ai_description', 1);
        })
        ->limit($limit)
        ->get();

        if ($translations->isEmpty()) {
            $this->info('No translations need AI content generation.');
            return;
        }

        $this->info("Processing {$translations->count()} translations...");

        $progressBar = $this->output->createProgressBar($translations->count());

        foreach ($translations as $translation) {
            try {
                $language = Language::find($translation->language_id);

                if (!$language) {
                    $this->warn("Language {$translation->language_id} not found for translation {$translation->id}");
                    $progressBar->advance();
                    continue;
                }

                $languageLabel = (string) $language->label;
                $hasUpdates = false;

                // Generate AI title if needed
                if ($translation->needs_ai_title && $translation->title) {
                    $aiTitle = $this->generateAiTitle(
                        (string) $translation->title,
                        $languageLabel
                    );

                    if ($aiTitle) {
                        $translation->ai_title = (string) $aiTitle;
                        $translation->needs_ai_title = 0;
                        $hasUpdates = true;
                    }
                }

                // Generate AI description if needed
                if ($translation->needs_ai_description && $translation->description) {
                    $aiDescription = $this->generateAiDescription(
                        (string) $translation->description,
                        $languageLabel
                    );

                    if ($aiDescription) {
                        $translation->ai_description = (string) $aiDescription;
                        $translation->needs_ai_description = 0;
                        $hasUpdates = true;
                    }
                }

                if ($hasUpdates) {
                    $translation->update([
                        'ai_title' => $translation->ai_title ?? null,
                        'needs_ai_title' => $translation->needs_ai_title,
                        'ai_description' => $translation->ai_description ?? null,
                        'needs_ai_description' => $translation->needs_ai_description,
                    ]);
                }

            } catch (\Exception $e) {
                $this->error("Error processing translation {$translation->id}: " . $e->getMessage());
            }

            $progressBar->advance();
        }

        $progressBar->finish();
        $this->newLine();
        $this->info('AI content generation completed successfully.');

        // Calculate and display execution time
        $endTime = microtime(true);
        $duration = $endTime - $startTime;

        $hours = (int)($duration / 3600);
        $minutes = (int)(($duration % 3600) / 60);
        $seconds = (int)($duration % 60);

        $this->info("Execution time: {$hours}h {$minutes}m {$seconds}s");
    }

    /**
     * Resolves OpenAI client from container override or SDK factory.
     */
    private function resolveOpenAiClient()
    {
        if (app()->bound('openai.client')) {
            return app('openai.client');
        }

        return \OpenAI::client(config('services.openai.api_key'));
    }

    /**
     * Generate an AI title using ChatGPT
     */
    private function generateAiTitle(string $originalTitle, string $language): ?string
    {
        try {
            $response = $this->client->chat()->create([
                'model' => 'gpt-5-nano',
                'messages' => [
                    [
                        'role' => 'system',
                        'content' => "You are my copywriter that will have to write for me in the most human way possible. Avoid words like: Strolling, Secluded, Cradled, Nestled, Glimpse, Perched, Lush, Embark !!!! The four main types of writing styles are persuasive, narrative, expository, and descriptive. The title needs to have about the same words as the original. Keep it concise and engaging. Use the same form of writing like the original: {$originalTitle}"
                    ],
                    [
                        'role' => 'user',
                        'content' => "Rewrite the following ad title. It's used for a travel website. IMPORTANT: Use passive voice! The ad title you need to rewrite: {$originalTitle}"
                    ]
                ],
                'temperature' => 1,
                'max_completion_tokens' => 150,
            ]);

            $aiTitle = trim($response->choices[0]->message->content);

            // Ensure it doesn't exceed the database column limit
            return substr($aiTitle, 0, 500);

        } catch (\Exception $e) {
            $this->error("Failed to generate AI title: " . $e->getMessage());
            return null;
        }
    }

    /**
     * Generate an AI description using ChatGPT
     */
    private function generateAiDescription(string $originalDescription, string $language): ?string
    {
        try {
            $response = $this->client->chat()->create([
                'model' => 'gpt-4o-mini',
                'messages' => [
                    [
                        'role' => 'system',
                        'content' => "You are my copywriter that will have to write for me in the most human way possible. Avoid words like: Strolling, Secluded, Cradled, Nestled, Glimpse, Perched, Lush, Embark !!!! The four main types of writing styles are persuasive, narrative, expository, and descriptive. The description needs to have about the same words as the original article. Use headlines ONLY IF the main text has headlines, if not, AVOID using them! KEEP THE SAME STYLE AND FORMAT. Use the same form of writing like here, it was written by you: {$originalDescription}"
                    ],
                    [
                        'role' => 'user',
                        'content' => "Rewrite the following ad description. It's used for a travel website. IMPORTANT: Use passive voice! The ad description you need to rewrite: {$originalDescription}"
                    ]
                ],
                'temperature' => 0.7,
                'max_completion_tokens' => 300,
            ]);

            $aiDescription = trim($response->choices[0]->message->content);

            // Ensure it doesn't exceed the database column limit
            return substr($aiDescription, 0, 1000);

        } catch (\Exception $e) {
            $this->error("Failed to generate AI description: " . $e->getMessage());
            return null;
        }
    }
}
