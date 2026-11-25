// Example data of the MultiWOZ page. It is synthetic: three short dialogues, their acts, states and rule records were written for this page, and no
// text or annotation is taken from the benchmark. The file is a script, not JSON, so that the page
// also shows it when index.html is opened straight from disk (file://), where a page cannot fetch
// a file. The value is plain JSON; example.json holds the same data for trying "Import data".
window.HR_EXAMPLE = [
 {
  "source": {
   "benchmark": "multiwoz",
   "synthetic": true,
   "note": "Invented for this page. It holds no text or annotation of the benchmark."
  },
  "dialogue_id": "EXAMPLE-A.json",
  "domains": [
   "restaurant"
  ],
  "turns": [
   {
    "index": 0,
    "speaker": "user",
    "text": "I would like an Italian restaurant in the north of town.",
    "acts": {
     "2.1": [
      {
       "act": "Restaurant-Inform",
       "slot": "Food",
       "value": "italian"
      },
      {
       "act": "Restaurant-Inform",
       "slot": "Area",
       "value": "north"
      }
     ],
     "2.2": [
      {
       "act": "Restaurant-Inform",
       "slot": "food",
       "value": "italian"
      },
      {
       "act": "Restaurant-Inform",
       "slot": "area",
       "value": "north"
      }
     ]
    },
    "state": {
     "2.1": {
      "restaurant-food": "italian",
      "restaurant-area": "north"
     },
     "2.2": {
      "restaurant-food": "italian",
      "restaurant-area": "north"
     },
     "2.4": {
      "restaurant-food": "italian",
      "restaurant-area": "north"
     }
    }
   },
   {
    "index": 1,
    "speaker": "system",
    "text": "Blue Heron Cafe is an Italian place in the north. Shall I book a table for you?",
    "acts": {
     "2.1": [
      {
       "act": "Restaurant-Inform",
       "slot": "Name",
       "value": "Blue Heron Cafe"
      },
      {
       "act": "Booking-Inform",
       "slot": "none",
       "value": "none"
      }
     ],
     "2.2": [
      {
       "act": "Restaurant-Inform",
       "slot": "name",
       "value": "Blue Heron Cafe"
      },
      {
       "act": "Booking-Inform",
       "slot": "none",
       "value": "none"
      }
     ]
    }
   },
   {
    "index": 2,
    "speaker": "user",
    "text": "Yes please, for 4 people on Friday at 19:00.",
    "acts": {
     "2.1": [
      {
       "act": "Restaurant-Inform",
       "slot": "Bookpeople",
       "value": "4"
      },
      {
       "act": "Restaurant-Inform",
       "slot": "Bookday",
       "value": "friday"
      },
      {
       "act": "Restaurant-Inform",
       "slot": "Booktime",
       "value": "19:00"
      }
     ],
     "2.2": [
      {
       "act": "Restaurant-Inform",
       "slot": "bookpeople",
       "value": "4"
      },
      {
       "act": "Restaurant-Inform",
       "slot": "bookday",
       "value": "friday"
      },
      {
       "act": "Restaurant-Inform",
       "slot": "booktime",
       "value": "19:00"
      }
     ]
    },
    "state": {
     "2.1": {
      "restaurant-food": "italian",
      "restaurant-area": "north",
      "restaurant-bookpeople": "4",
      "restaurant-bookday": "friday",
      "restaurant-booktime": "19:00"
     },
     "2.2": {
      "restaurant-food": "italian",
      "restaurant-area": "north",
      "restaurant-bookpeople": "4",
      "restaurant-bookday": "friday",
      "restaurant-booktime": "19:00",
      "restaurant-name": "blue heron cafe"
     },
     "2.4": {
      "restaurant-food": "italian",
      "restaurant-area": "north",
      "restaurant-bookpeople": "4",
      "restaurant-bookday": "friday",
      "restaurant-booktime": "19:00",
      "restaurant-name": "blue heron cafe"
     }
    },
    "census": {
     "2.1": {
      "label": "accept",
      "how": "explicit",
      "offer_kinds": {
       "restaurant": [
        "booking-inform",
        "inform-entity"
       ]
      },
      "offered": {
       "restaurant": {
        "name": [
         "blue heron cafe"
        ]
       }
      }
     },
     "2.2": {
      "label": "accept",
      "how": "explicit",
      "offer_kinds": {
       "restaurant": [
        "booking-inform",
        "inform-entity"
       ]
      },
      "offered": {
       "restaurant": {
        "name": [
         "blue heron cafe"
        ]
       }
      }
     }
    }
   },
   {
    "index": 3,
    "speaker": "system",
    "text": "Your table is booked. The reference number is EX12AB.",
    "acts": {
     "2.1": [
      {
       "act": "Booking-Book",
       "slot": "Ref",
       "value": "EX12AB"
      }
     ],
     "2.2": [
      {
       "act": "Booking-Book",
       "slot": "ref",
       "value": "EX12AB"
      }
     ]
    }
   },
   {
    "index": 4,
    "speaker": "user",
    "text": "Thanks. Is there also a cheap one in the south?",
    "acts": {
     "2.1": [
      {
       "act": "Restaurant-Inform",
       "slot": "Pricerange",
       "value": "cheap"
      },
      {
       "act": "Restaurant-Inform",
       "slot": "Area",
       "value": "south"
      }
     ],
     "2.2": [
      {
       "act": "Restaurant-Inform",
       "slot": "pricerange",
       "value": "cheap"
      },
      {
       "act": "Restaurant-Inform",
       "slot": "area",
       "value": "south"
      }
     ]
    },
    "state": {
     "2.1": {
      "restaurant-food": "italian",
      "restaurant-area": "south",
      "restaurant-bookpeople": "4",
      "restaurant-bookday": "friday",
      "restaurant-booktime": "19:00",
      "restaurant-pricerange": "cheap",
      "restaurant-name": "blue heron cafe"
     },
     "2.2": {
      "restaurant-food": "italian",
      "restaurant-area": "south",
      "restaurant-bookpeople": "4",
      "restaurant-bookday": "friday",
      "restaurant-booktime": "19:00",
      "restaurant-pricerange": "cheap"
     },
     "2.4": {
      "restaurant-area": "south",
      "restaurant-bookpeople": "4",
      "restaurant-bookday": "friday",
      "restaurant-booktime": "19:00",
      "restaurant-pricerange": "cheap"
     }
    }
   },
   {
    "index": 5,
    "speaker": "system",
    "text": "There are two: Rosa's Kitchen and The Lantern. Which one would you prefer?",
    "acts": {
     "2.1": [
      {
       "act": "Restaurant-Select",
       "slot": "Name",
       "value": "Rosa's Kitchen"
      },
      {
       "act": "Restaurant-Select",
       "slot": "Name",
       "value": "The Lantern"
      }
     ],
     "2.2": [
      {
       "act": "Restaurant-Select",
       "slot": "name",
       "value": "Rosa's Kitchen"
      },
      {
       "act": "Restaurant-Select",
       "slot": "name",
       "value": "The Lantern"
      }
     ]
    }
   },
   {
    "index": 6,
    "speaker": "user",
    "text": "What kind of food does The Lantern serve?",
    "acts": {
     "2.1": [
      {
       "act": "Restaurant-Request",
       "slot": "Food",
       "value": "?"
      },
      {
       "act": "Restaurant-Inform",
       "slot": "Name",
       "value": "The Lantern"
      }
     ],
     "2.2": [
      {
       "act": "Restaurant-Request",
       "slot": "food",
       "value": "?"
      }
     ]
    },
    "state": {
     "2.1": {
      "restaurant-food": "italian",
      "restaurant-area": "south",
      "restaurant-bookpeople": "4",
      "restaurant-bookday": "friday",
      "restaurant-booktime": "19:00",
      "restaurant-pricerange": "cheap",
      "restaurant-name": "the lantern"
     },
     "2.2": {
      "restaurant-food": "italian",
      "restaurant-area": "south",
      "restaurant-bookpeople": "4",
      "restaurant-bookday": "friday",
      "restaurant-booktime": "19:00",
      "restaurant-pricerange": "cheap"
     },
     "2.4": {
      "restaurant-area": "south",
      "restaurant-bookpeople": "4",
      "restaurant-bookday": "friday",
      "restaurant-booktime": "19:00",
      "restaurant-pricerange": "cheap"
     }
    },
    "census": {
     "2.1": {
      "label": "accept",
      "how": "implicit",
      "offer_kinds": {
       "restaurant": [
        "select"
       ]
      },
      "offered": {
       "restaurant": {
        "name": [
         "rosa's kitchen",
         "the lantern"
        ]
       }
      }
     },
     "2.2": {
      "label": "none",
      "how": null,
      "offer_kinds": {
       "restaurant": [
        "select"
       ]
      },
      "offered": {
       "restaurant": {
        "name": [
         "rosa's kitchen",
         "the lantern"
        ]
       }
      }
     }
    }
   },
   {
    "index": 7,
    "speaker": "system",
    "text": "The Lantern serves Thai food.",
    "acts": {
     "2.1": [
      {
       "act": "Restaurant-Inform",
       "slot": "Food",
       "value": "thai"
      }
     ],
     "2.2": [
      {
       "act": "Restaurant-Inform",
       "slot": "food",
       "value": "thai"
      }
     ]
    }
   }
  ]
 },
 {
  "source": {
   "benchmark": "multiwoz",
   "synthetic": true,
   "note": "Invented for this page. It holds no text or annotation of the benchmark."
  },
  "dialogue_id": "EXAMPLE-B.json",
  "domains": [
   "train",
   "hotel"
  ],
  "turns": [
   {
    "index": 0,
    "speaker": "user",
    "text": "I need a train from Avon to Brell on Tuesday, leaving after 09:00.",
    "acts": {
     "2.1": [
      {
       "act": "Train-Inform",
       "slot": "Departure",
       "value": "avon"
      },
      {
       "act": "Train-Inform",
       "slot": "Destination",
       "value": "brell"
      },
      {
       "act": "Train-Inform",
       "slot": "Day",
       "value": "tuesday"
      },
      {
       "act": "Train-Inform",
       "slot": "Leaveat",
       "value": "09:00"
      }
     ],
     "2.2": [
      {
       "act": "Train-Inform",
       "slot": "departure",
       "value": "avon"
      },
      {
       "act": "Train-Inform",
       "slot": "destination",
       "value": "brell"
      },
      {
       "act": "Train-Inform",
       "slot": "day",
       "value": "tuesday"
      },
      {
       "act": "Train-Inform",
       "slot": "leaveat",
       "value": "09:00"
      }
     ]
    },
    "state": {
     "2.1": {
      "train-departure": "avon",
      "train-destination": "brell",
      "train-day": "tuesday",
      "train-leaveat": "09:00"
     },
     "2.2": {
      "train-departure": "avon",
      "train-destination": "brell",
      "train-day": "tuesday",
      "train-leaveat": "09:00"
     },
     "2.4": {
      "train-departure": "avon",
      "train-destination": "brell",
      "train-day": "tuesday",
      "train-leaveat": "09:00"
     }
    }
   },
   {
    "index": 1,
    "speaker": "system",
    "text": "TR0001 leaves at 09:15 and arrives at 10:05. Would you like me to book it?",
    "acts": {
     "2.1": [
      {
       "act": "Train-Inform",
       "slot": "Trainid",
       "value": "TR0001"
      },
      {
       "act": "Train-Inform",
       "slot": "Leaveat",
       "value": "09:15"
      },
      {
       "act": "Train-Inform",
       "slot": "Arriveby",
       "value": "10:05"
      },
      {
       "act": "Train-OfferBook",
       "slot": "none",
       "value": "none"
      }
     ],
     "2.2": [
      {
       "act": "Train-Inform",
       "slot": "trainid",
       "value": "TR0001"
      },
      {
       "act": "Train-Inform",
       "slot": "leaveat",
       "value": "09:15"
      },
      {
       "act": "Train-Inform",
       "slot": "arriveby",
       "value": "10:05"
      },
      {
       "act": "Train-OfferBook",
       "slot": "none",
       "value": "none"
      }
     ]
    }
   },
   {
    "index": 2,
    "speaker": "user",
    "text": "No booking, thanks. I just need the price.",
    "acts": {
     "2.1": [
      {
       "act": "Train-Request",
       "slot": "Price",
       "value": "?"
      }
     ],
     "2.2": [
      {
       "act": "Train-Request",
       "slot": "price",
       "value": "?"
      }
     ]
    },
    "state": {
     "2.1": {
      "train-departure": "avon",
      "train-destination": "brell",
      "train-day": "tuesday",
      "train-leaveat": "09:00"
     },
     "2.2": {
      "train-departure": "avon",
      "train-destination": "brell",
      "train-day": "tuesday",
      "train-leaveat": "09:00"
     },
     "2.4": {
      "train-departure": "avon",
      "train-destination": "brell",
      "train-day": "tuesday",
      "train-leaveat": "09:00"
     }
    },
    "census": {
     "2.1": {
      "label": "accept",
      "how": "implicit",
      "offer_kinds": {
       "train": [
        "inform-entity",
        "offerbook"
       ]
      },
      "offered": {
       "train": {
        "trainid": [
         "tr0001"
        ]
       }
      }
     },
     "2.2": {
      "label": "accept",
      "how": "implicit",
      "offer_kinds": {
       "train": [
        "inform-entity",
        "offerbook"
       ]
      },
      "offered": {
       "train": {
        "trainid": [
         "tr0001"
        ]
       }
      }
     }
    }
   },
   {
    "index": 3,
    "speaker": "system",
    "text": "The ticket costs 12.50 pounds.",
    "acts": {
     "2.1": [
      {
       "act": "Train-Inform",
       "slot": "Price",
       "value": "12.50 pounds"
      }
     ],
     "2.2": [
      {
       "act": "Train-Inform",
       "slot": "price",
       "value": "12.50 pounds"
      }
     ]
    }
   },
   {
    "index": 4,
    "speaker": "user",
    "text": "Thanks. I also need a place to stay with free parking.",
    "acts": {
     "2.1": [
      {
       "act": "Hotel-Inform",
       "slot": "Parking",
       "value": "yes"
      }
     ],
     "2.2": [
      {
       "act": "Hotel-Inform",
       "slot": "parking",
       "value": "yes"
      }
     ]
    },
    "state": {
     "2.1": {
      "train-departure": "avon",
      "train-destination": "brell",
      "train-day": "tuesday",
      "train-leaveat": "09:00",
      "hotel-parking": "yes"
     },
     "2.2": {
      "train-departure": "avon",
      "train-destination": "brell",
      "train-day": "tuesday",
      "train-leaveat": "09:00",
      "hotel-parking": "yes"
     },
     "2.4": {
      "train-departure": "avon",
      "train-destination": "brell",
      "train-day": "tuesday",
      "train-leaveat": "09:00",
      "hotel-parking": "yes"
     }
    }
   },
   {
    "index": 5,
    "speaker": "system",
    "text": "I recommend the Harbour Inn, a 3-star hotel in the centre.",
    "acts": {
     "2.1": [
      {
       "act": "Hotel-Recommend",
       "slot": "Name",
       "value": "Harbour Inn"
      },
      {
       "act": "Hotel-Recommend",
       "slot": "Stars",
       "value": "3"
      },
      {
       "act": "Hotel-Recommend",
       "slot": "Area",
       "value": "centre"
      },
      {
       "act": "Hotel-Recommend",
       "slot": "Type",
       "value": "hotel"
      }
     ],
     "2.2": [
      {
       "act": "Hotel-Recommend",
       "slot": "name",
       "value": "Harbour Inn"
      },
      {
       "act": "Hotel-Recommend",
       "slot": "stars",
       "value": "3"
      },
      {
       "act": "Hotel-Recommend",
       "slot": "area",
       "value": "centre"
      },
      {
       "act": "Hotel-Recommend",
       "slot": "type",
       "value": "hotel"
      }
     ]
    }
   },
   {
    "index": 6,
    "speaker": "user",
    "text": "I would rather stay in a guesthouse.",
    "acts": {
     "2.1": [
      {
       "act": "Hotel-Inform",
       "slot": "Type",
       "value": "guesthouse"
      }
     ],
     "2.2": [
      {
       "act": "Hotel-Inform",
       "slot": "type",
       "value": "guesthouse"
      }
     ]
    },
    "state": {
     "2.1": {
      "train-departure": "avon",
      "train-destination": "brell",
      "train-day": "tuesday",
      "train-leaveat": "09:00",
      "hotel-parking": "yes",
      "hotel-type": "guest house"
     },
     "2.2": {
      "train-departure": "avon",
      "train-destination": "brell",
      "train-day": "tuesday",
      "train-leaveat": "09:00",
      "hotel-parking": "yes",
      "hotel-type": "guesthouse"
     },
     "2.4": {
      "train-departure": "avon",
      "train-destination": "brell",
      "train-day": "tuesday",
      "train-leaveat": "09:00",
      "hotel-parking": "yes",
      "hotel-type": "guesthouse"
     }
    },
    "census": {
     "2.1": {
      "label": "reject",
      "how": "counter-value",
      "offer_kinds": {
       "hotel": [
        "recommend"
       ]
      },
      "offered": {
       "hotel": {
        "area": [
         "centre"
        ],
        "name": [
         "harbour inn"
        ],
        "stars": [
         "3"
        ],
        "type": [
         "hotel"
        ]
       }
      }
     },
     "2.2": {
      "label": "reject",
      "how": "counter-value",
      "offer_kinds": {
       "hotel": [
        "recommend"
       ]
      },
      "offered": {
       "hotel": {
        "area": [
         "centre"
        ],
        "name": [
         "harbour inn"
        ],
        "stars": [
         "3"
        ],
        "type": [
         "hotel"
        ]
       }
      }
     }
    }
   },
   {
    "index": 7,
    "speaker": "system",
    "text": "Willow Guesthouse has free parking. Do you want me to book it?",
    "acts": {
     "2.1": [
      {
       "act": "Hotel-Inform",
       "slot": "Name",
       "value": "Willow Guesthouse"
      },
      {
       "act": "Hotel-Inform",
       "slot": "Parking",
       "value": "yes"
      },
      {
       "act": "Booking-Inform",
       "slot": "none",
       "value": "none"
      }
     ],
     "2.2": [
      {
       "act": "Hotel-Inform",
       "slot": "name",
       "value": "Willow Guesthouse"
      },
      {
       "act": "Hotel-Inform",
       "slot": "parking",
       "value": "yes"
      },
      {
       "act": "Booking-Inform",
       "slot": "none",
       "value": "none"
      }
     ]
    }
   },
   {
    "index": 8,
    "speaker": "user",
    "text": "Sounds good. 2 nights from Tuesday, for 1 person.",
    "acts": {
     "2.1": [],
     "2.2": [
      {
       "act": "Hotel-Inform",
       "slot": "bookstay",
       "value": "2"
      },
      {
       "act": "Hotel-Inform",
       "slot": "bookday",
       "value": "tuesday"
      },
      {
       "act": "Hotel-Inform",
       "slot": "bookpeople",
       "value": "1"
      }
     ]
    },
    "state": {
     "2.1": {
      "train-departure": "avon",
      "train-destination": "brell",
      "train-day": "tuesday",
      "train-leaveat": "09:00",
      "hotel-parking": "yes",
      "hotel-type": "guest house",
      "hotel-bookstay": "2",
      "hotel-bookday": "tuesday",
      "hotel-bookpeople": "1"
     },
     "2.2": {
      "train-departure": "avon",
      "train-destination": "brell",
      "train-day": "tuesday",
      "train-leaveat": "09:00",
      "hotel-parking": "yes",
      "hotel-type": "guesthouse",
      "hotel-bookstay": "2",
      "hotel-bookday": "tuesday",
      "hotel-bookpeople": "1"
     },
     "2.4": {
      "train-departure": "avon",
      "train-destination": "brell",
      "train-day": "tuesday",
      "train-leaveat": "09:00",
      "hotel-parking": "yes",
      "hotel-type": "guesthouse",
      "hotel-bookstay": "2",
      "hotel-bookday": "tuesday",
      "hotel-bookpeople": "1",
      "hotel-name": "willow guesthouse"
     }
    },
    "census": {
     "2.1": {
      "label": "none",
      "how": null,
      "offer_kinds": {
       "hotel": [
        "booking-inform",
        "inform-entity"
       ]
      },
      "offered": {
       "hotel": {
        "name": [
         "willow guesthouse"
        ]
       }
      }
     },
     "2.2": {
      "label": "accept",
      "how": "explicit",
      "offer_kinds": {
       "hotel": [
        "booking-inform",
        "inform-entity"
       ]
      },
      "offered": {
       "hotel": {
        "name": [
         "willow guesthouse"
        ]
       }
      }
     }
    }
   },
   {
    "index": 9,
    "speaker": "system",
    "text": "Booked. Your reference number is EX34CD.",
    "acts": {
     "2.1": [
      {
       "act": "Booking-Book",
       "slot": "Ref",
       "value": "EX34CD"
      }
     ],
     "2.2": [
      {
       "act": "Booking-Book",
       "slot": "ref",
       "value": "EX34CD"
      }
     ]
    }
   }
  ]
 },
 {
  "source": {
   "benchmark": "multiwoz",
   "synthetic": true,
   "note": "Invented for this page. It holds no text or annotation of the benchmark."
  },
  "dialogue_id": "EXAMPLE-C.json",
  "domains": [
   "attraction"
  ],
  "turns": [
   {
    "index": 0,
    "speaker": "user",
    "text": "Are there any museums in the east?",
    "acts": {
     "2.1": [
      {
       "act": "Attraction-Inform",
       "slot": "Type",
       "value": "museum"
      },
      {
       "act": "Attraction-Inform",
       "slot": "Area",
       "value": "east"
      }
     ],
     "2.2": [
      {
       "act": "Attraction-Inform",
       "slot": "type",
       "value": "museum"
      },
      {
       "act": "Attraction-Inform",
       "slot": "area",
       "value": "east"
      }
     ]
    },
    "state": {
     "2.1": {
      "attraction-type": "museum",
      "attraction-area": "east"
     },
     "2.2": {
      "attraction-type": "museum",
      "attraction-area": "east"
     },
     "2.4": {
      "attraction-type": "museum",
      "attraction-area": "east"
     }
    }
   },
   {
    "index": 1,
    "speaker": "system",
    "text": "Tide Museum is in the east, and entry is free.",
    "acts": {
     "2.1": [
      {
       "act": "Attraction-Inform",
       "slot": "Name",
       "value": "Tide Museum"
      },
      {
       "act": "Attraction-Inform",
       "slot": "Fee",
       "value": "free"
      }
     ],
     "2.2": [
      {
       "act": "Attraction-Inform",
       "slot": "name",
       "value": "Tide Museum"
      },
      {
       "act": "Attraction-Inform",
       "slot": "fee",
       "value": "free"
      }
     ]
    }
   },
   {
    "index": 2,
    "speaker": "user",
    "text": "Great, what is the address?",
    "acts": {
     "2.1": [
      {
       "act": "Attraction-Request",
       "slot": "Address",
       "value": "?"
      }
     ],
     "2.2": [
      {
       "act": "Attraction-Request",
       "slot": "address",
       "value": "?"
      }
     ]
    },
    "state": {
     "2.1": {
      "attraction-type": "museum",
      "attraction-area": "east"
     },
     "2.2": {
      "attraction-type": "museum",
      "attraction-area": "east"
     },
     "2.4": {
      "attraction-type": "museum",
      "attraction-area": "east",
      "attraction-name": "tide museum"
     }
    },
    "census": {
     "2.1": {
      "label": "accept",
      "how": "implicit",
      "offer_kinds": {
       "attraction": [
        "inform-entity"
       ]
      },
      "offered": {
       "attraction": {
        "name": [
         "tide museum"
        ]
       }
      }
     },
     "2.2": {
      "label": "accept",
      "how": "implicit",
      "offer_kinds": {
       "attraction": [
        "inform-entity"
       ]
      },
      "offered": {
       "attraction": {
        "name": [
         "tide museum"
        ]
       }
      }
     }
    }
   },
   {
    "index": 3,
    "speaker": "system",
    "text": "It is at 5 Quay Lane.",
    "acts": {
     "2.1": [
      {
       "act": "Attraction-Inform",
       "slot": "Address",
       "value": "5 Quay Lane"
      }
     ],
     "2.2": [
      {
       "act": "Attraction-Inform",
       "slot": "address",
       "value": "5 Quay Lane"
      }
     ]
    }
   },
   {
    "index": 4,
    "speaker": "user",
    "text": "Thank you, goodbye.",
    "acts": {
     "2.1": [],
     "2.2": [
      {
       "act": "general-thank",
       "slot": "none",
       "value": "none"
      },
      {
       "act": "general-bye",
       "slot": "none",
       "value": "none"
      }
     ]
    },
    "state": {
     "2.1": {
      "attraction-type": "museum",
      "attraction-area": "east"
     },
     "2.2": {
      "attraction-type": "museum",
      "attraction-area": "east"
     },
     "2.4": {
      "attraction-type": "museum",
      "attraction-area": "east",
      "attraction-name": "tide museum"
     }
    }
   },
   {
    "index": 5,
    "speaker": "system",
    "text": "Goodbye.",
    "acts": {
     "2.1": [
      {
       "act": "general-bye",
       "slot": "none",
       "value": "none"
      }
     ],
     "2.2": [
      {
       "act": "general-bye",
       "slot": "none",
       "value": "none"
      }
     ]
    }
   }
  ]
 }
];
