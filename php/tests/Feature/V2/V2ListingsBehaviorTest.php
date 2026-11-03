<?php

namespace Tests\Feature\V2;

use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Config;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;
use Tests\TestCase;

/**
 * Behavior-level tests for V2 listings endpoints.
 *
 * This suite validates stable error contracts around missing listing resources.
 */
class V2ListingsBehaviorTest extends TestCase
{
    /**
     * Prepares isolated sqlite schema used by listing behavior tests.
     */
    protected function setUp(): void
    {
        parent::setUp();

        // Keep listing behavior tests isolated from default database state.
        $databasePath = storage_path('framework/testing-v2-listings.sqlite');
        if (!file_exists($databasePath)) {
            touch($databasePath);
        }

        Config::set('database.default', 'sqlite');
        Config::set('database.connections.sqlite.database', $databasePath);
        Config::set('cache.stores.redis.driver', 'array');

        DB::purge('sqlite');
        DB::reconnect('sqlite');

        $this->prepareSchema();
        $this->truncateData();
        $this->seedDefaultLanguage();
    }

    /**
     * Cleans fixture data after each test execution.
     */
    protected function tearDown(): void
    {
        $this->truncateData();
        parent::tearDown();
    }

    /**
     * Verifies /api/v2/listings/{id} returns 422 contract for missing listing ids.
     */
    public function test_listings_show_returns_422_for_missing_listing()
    {
        // The endpoint should keep the existing invalid_data contract for unknown IDs.
        $response = $this->getJson('/api/v2/listings/999999');

        $response->assertStatus(422);
        $response->assertJsonStructure([
            'message',
            'errors' => ['listing_id'],
        ]);
    }

    /**
     * Verifies nearby destinations endpoint returns 422 when listing does not exist.
     */
    public function test_nearby_destinations_returns_422_for_missing_listing()
    {
        $response = $this->getJson('/api/v2/listings/999999/nearbydestinations');

        $response->assertStatus(422);
        $response->assertJsonStructure([
            'message',
            'errors' => ['listing_id'],
        ]);
    }

    /**
     * Verifies nearby listings endpoint returns 422 when listing does not exist.
     */
    public function test_nearby_listings_returns_422_for_missing_listing()
    {
        $response = $this->getJson('/api/v2/listings/999999/nearbylistings');

        $response->assertStatus(422);
        $response->assertJsonStructure([
            'message',
            'errors' => ['listing_id'],
        ]);
    }

    /**
     * Verifies showFullDetails prefers AI title/description and exposes decoded details.json_data.
     */
    public function test_show_full_details_uses_ai_text_and_decodes_json_data()
    {
        DB::table('listings')->insert([
            'id' => 2001,
            'destination_id' => 1,
            'status' => 'ACTIVE',
            'noOfReviews' => 11,
            'averageRating' => 4.7,
        ]);

        DB::table('listing_translations')->insert([
            'listing_id' => 2001,
            'language_id' => 1,
            'title' => 'Original title',
            'ai_title' => 'AI title',
            'description' => 'Original description',
            'ai_description' => 'AI description',
            'json_data' => json_encode(['sample' => 'value']),
        ]);

        $response = $this->getJson('/api/v2/listings/2001/fulldetails');

        $response->assertOk();
        $response->assertJsonFragment(['id' => 2001]);
        $response->assertJsonPath('listing.title', 'AI title');
        $response->assertJsonPath('listing.description', 'AI description');
        $response->assertJsonPath('listing.details.json_data.sample', 'value');
        $response->assertJsonMissingPath('listing.json_data');
    }

    /**
     * Verifies show endpoint also applies AI title/description precedence through ListingResource.
     */
    public function test_show_uses_ai_title_and_ai_description_in_resource()
    {
        DB::table('listings')->insert([
            'id' => 2002,
            'destination_id' => 1,
            'status' => 'ACTIVE',
            'noOfReviews' => 8,
            'averageRating' => 4.2,
        ]);

        DB::table('listing_translations')->insert([
            'listing_id' => 2002,
            'language_id' => 1,
            'title' => 'Original title',
            'ai_title' => 'AI title resource',
            'description' => 'Original description',
            'ai_description' => 'AI description resource',
            'json_data' => json_encode([
                'logistics' => [
                    'travelerPickup' => ['locations' => []],
                    'start' => [['description' => 'Start point']],
                ],
                'ticketInfo' => [],
                'languageGuides' => [],
                'inclusions' => [],
                'exclusions' => [],
                'additionalInfo' => [],
                'cancellationPolicy' => [],
                'productUrl' => 'https://example.test/product',
                'itinerary' => ['itineraryItems' => [], 'activityInfo' => ['description' => 'Activity']],
                'supplier' => ['name' => 'Supplier'],
                'bookingRequirements' => [],
            ]),
        ]);

        // Minimal related records needed by ListingResource transformation logic.
        DB::table('listing_images')->insert([
            'id' => 901,
            'listing_id' => 2002,
            'src' => 'https://img.test/1.jpg',
        ]);

        $response = $this->getJson('/api/v2/listings/2002');

        $response->assertOk();
        $response->assertJsonPath('listing.id', 2002);
        $response->assertJsonPath('listing.title', 'AI title resource');
        $response->assertJsonPath('listing.description', 'AI description resource');
    }

    /**
     * Verifies searchInTitle returns only title-matching active listings with images.
     */
    public function test_search_in_title_filters_by_matching_title_text()
    {
        DB::table('listings')->insert([
            [
                'id' => 2101,
                'destination_id' => 1,
                'status' => 'ACTIVE',
                'noOfReviews' => 12,
                'averageRating' => 4.8,
            ],
            [
                'id' => 2102,
                'destination_id' => 1,
                'status' => 'ACTIVE',
                'noOfReviews' => 9,
                'averageRating' => 4.1,
            ],
        ]);

        DB::table('listing_translations')->insert([
            [
                'listing_id' => 2101,
                'language_id' => 1,
                'title' => 'Paris Museum Tour',
                'description' => 'Desc',
                'json_data' => '{}',
            ],
            [
                'listing_id' => 2102,
                'language_id' => 1,
                'title' => 'Lyon Food Walk',
                'description' => 'Desc',
                'json_data' => '{}',
            ],
        ]);

        // searchInTitle requires image relation due has('images') constraint.
        DB::table('listing_images')->insert([
            ['listing_id' => 2101, 'src' => 'https://img.test/2101.jpg'],
            ['listing_id' => 2102, 'src' => 'https://img.test/2102.jpg'],
        ]);

        $response = $this->getJson('/api/v2/listings/searchInTitle?text=Museum');

        $response->assertOk();
        $response->assertJsonFragment(['id' => 2101, 'title' => 'Paris Museum Tour']);
        $response->assertJsonMissing(['id' => 2102]);
    }

    /**
     * Verifies search applies destination filter and keeps pagination metadata.
     */
    public function test_search_filters_by_destination_and_returns_meta()
    {
        DB::table('providers_destinations')->insert([
            ['id' => 301, 'destinationName' => 'Paris', 'destinationType' => 'CITY'],
            ['id' => 302, 'destinationName' => 'Lyon', 'destinationType' => 'CITY'],
        ]);

        $listings = [];
        $translations = [];
        $images = [];
        $requirements = [];
        $itineraries = [];
        $ratings = [];
        for ($id = 2201; $id <= 2205; $id++) {
            $listings[] = [
                'id' => $id,
                'destination_id' => 301,
                'status' => 'ACTIVE',
                'noOfReviews' => 20,
                'averageRating' => 4.9,
            ];
            $translations[] = ['listing_id' => $id, 'language_id' => 1, 'title' => "Paris {$id}", 'description' => 'Desc', 'json_data' => '{}'];
            $images[] = ['listing_id' => $id, 'src' => "https://img.test/{$id}.jpg"];
            $requirements[] = ['listing_id' => $id, 'max_travelers_per_booking' => 10];
            $itineraries[] = ['listing_id' => $id, 'fixed_duration_in_minutes' => 120];
            $ratings[] = ['listing_id' => $id, 'rating' => 95];
        }
        $listings[] = [
            'id' => 2206,
            'destination_id' => 302,
            'status' => 'ACTIVE',
            'noOfReviews' => 15,
            'averageRating' => 4.7,
        ];
        $translations[] = ['listing_id' => 2206, 'language_id' => 1, 'title' => 'Lyon One', 'description' => 'Desc', 'json_data' => '{}'];
        $images[] = ['listing_id' => 2206, 'src' => 'https://img.test/2206.jpg'];
        $requirements[] = ['listing_id' => 2206, 'max_travelers_per_booking' => 12];
        $itineraries[] = ['listing_id' => 2206, 'fixed_duration_in_minutes' => 90];
        $ratings[] = ['listing_id' => 2206, 'rating' => 80];

        DB::table('listings')->insert($listings);
        DB::table('listing_translations')->insert($translations);
        DB::table('listing_images')->insert($images);
        DB::table('listing_booking_requirements')->insert($requirements);
        DB::table('listing_itineraries')->insert($itineraries);
        DB::table('listing_internal_ratings')->insert($ratings);

        $response = $this->getJson('/api/v2/listings/search?destination_id=301&page=1&page_size=10');

        $response->assertOk();
        $response->assertJsonFragment(['id' => 2201]);
        $response->assertJsonMissing(['id' => 2206]);
        $response->assertJsonPath('meta.page', '1');
        $response->assertJsonPath('meta.pageSize', '10');
    }

    /**
     * Verifies search uses cache-driven France destination expansion when destination_id is 3106.
     */
    public function test_search_uses_cached_france_destination_ids_for_country_scope()
    {
        DB::table('providers_destinations')->insert([
            ['id' => 3106, 'destinationName' => 'France', 'destinationType' => 'COUNTRY'],
            ['id' => 401, 'destinationName' => 'Paris', 'destinationType' => 'CITY'],
            ['id' => 402, 'destinationName' => 'Nice', 'destinationType' => 'CITY'],
            ['id' => 403, 'destinationName' => 'Lyon', 'destinationType' => 'CITY'],
            ['id' => 499, 'destinationName' => 'Berlin', 'destinationType' => 'CITY'],
        ]);

        // Country-level search for France should expand using precomputed cached city ids.
        Cache::store('redis')->put('citiesRelatedToFrance', [401, 402, 403]);

        $listings = [];
        $translations = [];
        $images = [];
        $requirements = [];
        $itineraries = [];
        $ratings = [];
        foreach ([2301 => 401, 2302 => 402, 2303 => 403, 2304 => 401, 2305 => 402] as $listingId => $destinationId) {
            $listings[] = [
                'id' => $listingId,
                'destination_id' => $destinationId,
                'status' => 'ACTIVE',
                'noOfReviews' => 12,
                'averageRating' => 4.6,
            ];
            $translations[] = [
                'listing_id' => $listingId,
                'language_id' => 1,
                'title' => "France {$listingId}",
                'description' => 'Desc',
                'json_data' => '{}',
            ];
            $images[] = ['listing_id' => $listingId, 'src' => "https://img.test/{$listingId}.jpg"];
            $requirements[] = ['listing_id' => $listingId, 'max_travelers_per_booking' => 8];
            $itineraries[] = ['listing_id' => $listingId, 'fixed_duration_in_minutes' => 100];
            $ratings[] = ['listing_id' => $listingId, 'rating' => 90];
        }

        // This listing is outside cached france ids and must not appear in response.
        $listings[] = [
            'id' => 2399,
            'destination_id' => 499,
            'status' => 'ACTIVE',
            'noOfReviews' => 13,
            'averageRating' => 4.7,
        ];
        $translations[] = ['listing_id' => 2399, 'language_id' => 1, 'title' => 'Outside France Cache', 'description' => 'Desc', 'json_data' => '{}'];
        $images[] = ['listing_id' => 2399, 'src' => 'https://img.test/2399.jpg'];
        $requirements[] = ['listing_id' => 2399, 'max_travelers_per_booking' => 10];
        $itineraries[] = ['listing_id' => 2399, 'fixed_duration_in_minutes' => 90];
        $ratings[] = ['listing_id' => 2399, 'rating' => 95];

        DB::table('listings')->insert($listings);
        DB::table('listing_translations')->insert($translations);
        DB::table('listing_images')->insert($images);
        DB::table('listing_booking_requirements')->insert($requirements);
        DB::table('listing_itineraries')->insert($itineraries);
        DB::table('listing_internal_ratings')->insert($ratings);

        $response = $this->getJson('/api/v2/listings/search?destination_id=3106&page=1&page_size=10');

        $response->assertOk();
        $response->assertJsonFragment(['id' => 2301]);
        $response->assertJsonFragment(['id' => 2305]);
        $response->assertJsonMissing(['id' => 2399]);
    }

    /**
     * Verifies listings index returns invalid_data contract when locale has no mapped language row.
     */
    public function test_listings_index_returns_422_when_language_is_missing()
    {
        app()->setLocale('zz');

        $response = $this->getJson('/api/v2/listings');

        $response->assertStatus(422);
        $response->assertJsonStructure([
            'message',
            'errors' => ['language'],
        ]);
    }

    /**
     * Verifies listings show returns invalid_data contract when locale has no mapped language row.
     */
    public function test_listings_show_returns_422_when_language_is_missing()
    {
        app()->setLocale('zz');

        $response = $this->getJson('/api/v2/listings/2002');

        $response->assertStatus(422);
        $response->assertJsonStructure([
            'message',
            'errors' => ['language'],
        ]);
    }

    /**
     * Verifies listings search returns invalid_data contract when locale has no mapped language row.
     */
    public function test_listings_search_returns_422_when_language_is_missing()
    {
        app()->setLocale('zz');

        $response = $this->getJson('/api/v2/listings/search?page=1&page_size=10');

        $response->assertStatus(422);
        $response->assertJsonStructure([
            'message',
            'errors' => ['language'],
        ]);
    }

    /**
     * Verifies listings searchInTitle returns invalid_data contract when locale has no mapped language row.
     */
    public function test_listings_search_in_title_returns_422_when_language_is_missing()
    {
        app()->setLocale('zz');

        $response = $this->getJson('/api/v2/listings/searchInTitle?text=Paris');

        $response->assertStatus(422);
        $response->assertJsonStructure([
            'message',
            'errors' => ['language'],
        ]);
    }

    /**
     * Verifies listings showFullDetails returns invalid_data contract when locale has no mapped language row.
     */
    public function test_listings_show_full_details_returns_422_when_language_is_missing()
    {
        app()->setLocale('zz');

        $response = $this->getJson('/api/v2/listings/2001/fulldetails');

        $response->assertStatus(422);
        $response->assertJsonStructure([
            'message',
            'errors' => ['language'],
        ]);
    }

    /**
     * Verifies listings nearbylistings returns invalid_data contract when locale has no mapped language row.
     */
    public function test_listings_nearby_listings_returns_422_when_language_is_missing()
    {
        app()->setLocale('zz');

        $response = $this->getJson('/api/v2/listings/2001/nearbylistings');

        $response->assertStatus(422);
        $response->assertJsonStructure([
            'message',
            'errors' => ['language'],
        ]);
    }

    /**
     * Creates only tables required to execute listing error-path queries.
     */
    private function prepareSchema(): void
    {
        if (!Schema::hasTable('languages')) {
            Schema::create('languages', function (Blueprint $table) {
                $table->increments('id');
                $table->string('code')->nullable();
                $table->string('label')->nullable();
                $table->timestamps();
            });
        }

        if (!Schema::hasTable('listings')) {
            Schema::create('listings', function (Blueprint $table) {
                $table->increments('id');
                $table->integer('destination_id')->nullable();
                $table->string('status')->nullable();
                $table->integer('noOfReviews')->default(0);
                $table->decimal('averageRating', 8, 2)->default(0);
                $table->decimal('latitude', 10, 7)->nullable();
                $table->decimal('longitude', 10, 7)->nullable();
                $table->timestamps();
            });
        }

        if (!Schema::hasTable('providers_destinations')) {
            Schema::create('providers_destinations', function (Blueprint $table) {
                $table->increments('id');
                $table->string('destinationName')->nullable();
                $table->string('destinationType')->nullable();
                $table->decimal('latitude', 10, 7)->nullable();
                $table->decimal('longitude', 10, 7)->nullable();
                $table->timestamps();
            });
        }

        if (!Schema::hasTable('listing_translations')) {
            Schema::create('listing_translations', function (Blueprint $table) {
                $table->increments('id');
                $table->integer('listing_id');
                $table->integer('language_id');
                $table->string('title')->nullable();
                $table->string('ai_title')->nullable();
                $table->text('description')->nullable();
                $table->text('ai_description')->nullable();
                $table->text('json_data')->nullable();
                $table->timestamps();
            });
        }

        if (!Schema::hasTable('listing_images')) {
            Schema::create('listing_images', function (Blueprint $table) {
                $table->increments('id');
                $table->integer('listing_id');
                $table->string('src')->nullable();
                $table->timestamps();
            });
        }

        if (!Schema::hasTable('listing_prices')) {
            Schema::create('listing_prices', function (Blueprint $table) {
                $table->increments('id');
                $table->integer('listing_id');
                $table->decimal('from_price', 10, 2)->nullable();
                $table->string('currency')->nullable();
                $table->text('json_data')->nullable();
                $table->timestamps();
            });
        }

        if (!Schema::hasTable('listing_reviews')) {
            Schema::create('listing_reviews', function (Blueprint $table) {
                $table->increments('id');
                $table->integer('listing_id');
                $table->integer('rating')->nullable();
                $table->timestamps();
            });
        }

        if (!Schema::hasTable('listings_unavailable_dates')) {
            Schema::create('listings_unavailable_dates', function (Blueprint $table) {
                $table->increments('id');
                $table->integer('listing_id');
                $table->date('date_unavailable')->nullable();
                $table->timestamps();
            });
        }

        if (!Schema::hasTable('listing_itineraries')) {
            Schema::create('listing_itineraries', function (Blueprint $table) {
                $table->increments('id');
                $table->integer('listing_id');
                $table->integer('fixed_duration_in_minutes')->nullable();
                $table->integer('variable_duration_from_minutes')->nullable();
                $table->integer('variable_duration_to_minutes')->nullable();
                $table->timestamps();
            });
        }

        if (!Schema::hasTable('listing_subcategories')) {
            Schema::create('listing_subcategories', function (Blueprint $table) {
                $table->increments('id');
                $table->integer('listing_id');
                $table->integer('subcategory_id')->nullable();
                $table->timestamps();
            });
        }

        if (!Schema::hasTable('subcategories_v2')) {
            Schema::create('subcategories_v2', function (Blueprint $table) {
                $table->increments('id');
                $table->string('key')->nullable();
                $table->timestamps();
            });
        }

        if (!Schema::hasTable('listing_booking_requirements')) {
            Schema::create('listing_booking_requirements', function (Blueprint $table) {
                $table->increments('id');
                $table->integer('listing_id');
                $table->integer('max_travelers_per_booking')->nullable();
                $table->timestamps();
            });
        }

        if (!Schema::hasTable('listing_internal_ratings')) {
            Schema::create('listing_internal_ratings', function (Blueprint $table) {
                $table->increments('id');
                $table->integer('listing_id');
                $table->integer('rating')->nullable();
                $table->timestamps();
            });
        }

        if (!Schema::hasTable('listing_itinerary_items')) {
            Schema::create('listing_itinerary_items', function (Blueprint $table) {
                $table->increments('id');
                $table->integer('listing_itinerary_id');
                $table->integer('listing_location_id')->nullable();
                $table->string('location_ref')->nullable();
                $table->text('description')->nullable();
                $table->timestamps();
            });
        }

        if (!Schema::hasTable('listing_logistics')) {
            Schema::create('listing_logistics', function (Blueprint $table) {
                $table->increments('id');
                $table->integer('listing_id');
                $table->integer('start_listing_location_id')->nullable();
                $table->integer('end_listing_location_id')->nullable();
                $table->string('start_location_description')->nullable();
                $table->string('end_location_description')->nullable();
                $table->timestamps();
            });
        }

        if (!Schema::hasTable('listing_locations')) {
            Schema::create('listing_locations', function (Blueprint $table) {
                $table->increments('id');
                $table->string('name')->nullable();
                $table->string('reference')->nullable();
                $table->timestamps();
            });
        }
    }

    /**
     * Seeds active locale used by getDbLanguage() in base controller.
     */
    private function seedDefaultLanguage(): void
    {
        DB::table('languages')->insert([
            'id' => 1,
            'code' => 'en',
            'label' => 'English',
        ]);
    }

    /**
     * Truncates fixture tables used by this suite.
     */
    private function truncateData(): void
    {
        DB::table('listing_images')->delete();
        DB::table('listing_reviews')->delete();
        DB::table('listings_unavailable_dates')->delete();
        DB::table('listing_prices')->delete();
        DB::table('listing_internal_ratings')->delete();
        DB::table('listing_booking_requirements')->delete();
        DB::table('listing_subcategories')->delete();
        DB::table('subcategories_v2')->delete();
        DB::table('listing_itinerary_items')->delete();
        DB::table('listing_itineraries')->delete();
        DB::table('listing_logistics')->delete();
        DB::table('listing_locations')->delete();
        DB::table('listing_translations')->delete();
        DB::table('listings')->delete();
        DB::table('providers_destinations')->delete();
        DB::table('languages')->delete();
    }
}
