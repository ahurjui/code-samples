<?php

namespace App\Http\Requests\V2;

use Illuminate\Foundation\Http\FormRequest;

/**
 * Viator Partner API proxy POST: body is passed through to Viator as JSON (see controllers).
 * Validation is intentionally minimal; Viator enforces the contract.
 */
class ViatorPartnerJsonPostRequest extends FormRequest
{
    public function authorize(): bool
    {
        return true;
    }

    public function rules(): array
    {
        return [];
    }
}
