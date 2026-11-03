<?php

namespace App\Http\Requests;

use Illuminate\Foundation\Http\FormRequest;

class SearchListingsRequest extends FormRequest
{
    /**
     * Determine if the user is authorized to make this request.
     *
     * @return bool
     */
    public function authorize()
    {
        return true;
    }

    /**
     * Get the validation rules that apply to the request.
     *
     * @return array
     */
    public function rules()
    {
        return [
            'destination_id'                    =>  'sometimes|exists:providers_destinations,id',
            'category_id'                       =>  'sometimes|exists:listings,category_id',
            'subcategory_id'                    =>  'sometimes|numeric|integer',
            'start_date'                        =>  'sometimes|date|date_format:Y-m-d|after_or_equal:today',
            'end_date'                          =>  'sometimes|required_with:start_date|date|date_format:Y-m-d|after_or_equal:start_date',
            'page'                              =>  'required_with:page_size|numeric|min:1',
            'page_size'                         =>  'required_with:page|numeric|min:1',
            'shuffle'                           =>  'sometimes|boolean',
            'minimum_rating'                    =>  'sometimes|numeric',
            'minimum_number_of_reviews'         =>  'sometimes|numeric',
            'min_price'                         =>  'sometimes|numeric',
            'max_price'                         =>  'sometimes|numeric',

            'available_hours'                   =>  'sometimes|array',
            'available_hours.starts_before_12'  =>  'sometimes|boolean',
            'available_hours.starts_after_12'   =>  'sometimes|boolean',
            'available_hours.starts_after_17'   =>  'sometimes|boolean',

            'duration'                          =>  'sometimes|array',
            'duration.up_to_1_hour'             =>  'sometimes|boolean',
            'duration.1_to_4_hours'             =>  'sometimes|boolean',
            'duration.4_hours_to_24_hours'      =>  'sometimes|boolean',
            'duration.1_to_3_days'              =>  'sometimes|boolean',
            'duration.3_days_plus'              =>  'sometimes|boolean',
        ];
    }
}
