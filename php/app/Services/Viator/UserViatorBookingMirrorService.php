<?php

namespace App\Services\Viator;

use App\Entities\UserViatorBooking;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

/**
 * Persists a **local mirror** of Viator booking refs per FranceRent user. Call only **after** Viator
 * returns success (or after you successfully refresh from {@see ViatorHttpClient} `/bookings/status`),
 * so your DB never leads Viator.
 */
final class UserViatorBookingMirrorService
{
    /**
     * After a successful `cart/book` (or when you first have a stable `viator_booking_ref` for this user), upsert a row.
     *
     * @param  array<string, mixed>|null  $statusSnapshot  Optional `POST /bookings/status` (or book response) JSON to cache.
     */
    public function recordAfterSuccessfulBook(
        int $userId,
        string $viatorBookingRef,
        ?string $partnerBookingRef = null,
        ?string $partnerCartRef = null,
        ?string $productCode = null,
        ?string $title = null,
        ?array $statusSnapshot = null,
    ): UserViatorBooking {
        $ref = trim($viatorBookingRef);
        if ($ref === '') {
            throw new \InvalidArgumentException('viator_booking_ref is required');
        }

        return DB::transaction(function () use ($userId, $ref, $partnerBookingRef, $partnerCartRef, $productCode, $title, $statusSnapshot) {
            $row = UserViatorBooking::query()
                ->where('viator_booking_ref', $ref)
                ->lockForUpdate()
                ->first();

            if ($row !== null && (int) $row->user_id !== $userId) {
                throw new \InvalidArgumentException('viator_booking_ref already associated with another user');
            }

            $now = Carbon::now();
            $data = [
                'user_id' => $userId,
                'viator_booking_ref' => $ref,
                'partner_booking_ref' => $partnerBookingRef,
                'partner_cart_ref' => $partnerCartRef,
                'product_code' => $productCode,
                'title' => $title,
                'last_status_json' => $statusSnapshot,
                'last_status_synced_at' => $statusSnapshot !== null ? $now : $row?->last_status_synced_at,
            ];

            if ($row === null) {
                return UserViatorBooking::query()->create(
                    $data + ['local_status' => $this->deriveLocalStatus($statusSnapshot)]
                );
            }

            $row->fill($data);
            if (isset($data['last_status_json'])) {
                $row->local_status = $this->deriveLocalStatus($statusSnapshot) ?? $row->local_status;
            }
            $row->save();

            return $row;
        });
    }

    /**
     * After a successful `POST /bookings/status` (or to reconcile), update the mirror for that user and ref.
     *
     * @param  array<string, mixed>  $statusJson  Parsed JSON from Viator.
     */
    public function updateFromStatusResponse(int $userId, string $viatorBookingRef, array $statusJson): UserViatorBooking
    {
        $row = $this->getOwnedOrFail($userId, $viatorBookingRef);
        $row->last_status_json = $statusJson;
        $row->last_status_synced_at = Carbon::now();
        $row->local_status = $this->deriveLocalStatus($statusJson) ?? $row->local_status;
        $row->save();

        return $row;
    }

    /**
     * After a successful `POST /bookings/{ref}/cancel` (Viator), mark the local row cancelled.
     *
     * @param  array<string, mixed>|null  $lastSnapshot  Optional last JSON (e.g. from cancel response) to merge into last_status_json.
     */
    public function markCancelledAfterViatorSuccess(
        int $userId,
        string $viatorBookingRef,
        ?array $lastSnapshot = null,
    ): UserViatorBooking {
        $row = $this->getOwnedOrFail($userId, $viatorBookingRef);
        if ($lastSnapshot !== null) {
            $row->last_status_json = $lastSnapshot;
        }
        $row->cancelled_at = Carbon::now();
        $row->local_status = 'cancelled';
        $row->last_status_synced_at = Carbon::now();
        $row->save();

        return $row;
    }

    public function findOwnedByUser(int $userId, string $viatorBookingRef): ?UserViatorBooking
    {
        $ref = trim($viatorBookingRef);

        return UserViatorBooking::query()
            ->where('user_id', $userId)
            ->where('viator_booking_ref', $ref)
            ->first();
    }

    private function getOwnedOrFail(int $userId, string $viatorBookingRef): UserViatorBooking
    {
        $row = $this->findOwnedByUser($userId, $viatorBookingRef);
        if ($row === null) {
            throw new \InvalidArgumentException('No local Viator booking for this user and ref');
        }

        return $row;
    }

    /**
     * @param  array<string, mixed>|null  $json
     */
    private function deriveLocalStatus(?array $json): ?string
    {
        if ($json === null) {
            return null;
        }
        if (isset($json['status']) && is_string($json['status'])) {
            return $json['status'];
        }
        if (isset($json['bookingStatus']) && is_string($json['bookingStatus'])) {
            return $json['bookingStatus'];
        }

        return null;
    }
}
